import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from bot_controller import BotController

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Beerthuizen Management Chatbot API")
bot = BotController()

# In-memory message buffers for double-texting management (BUG #3 Fix)
# Format: { phone_number: {"messages": [...], "name": str, "chat_id": str, "task": asyncio.Task} }
message_buffers = {}
buffer_lock = asyncio.Lock()

async def flush_buffer(phone: str):
    """
    Consolidates buffered messages for a phone number and triggers chatbot processing.
    """
    await asyncio.sleep(10.0)  # Wait for 10 seconds so all rapid messages are combined
    
    async with buffer_lock:
        if phone not in message_buffers:
            return
        
        user_data = message_buffers.pop(phone)
        messages = user_data["messages"]
        name = user_data["name"]
        chat_id = user_data["chat_id"]
        
    combined_message = " ".join(messages).strip()
    
    if combined_message:
        logger.info(f"Flushing buffer for {phone}. Combined message: '{combined_message}'")
        try:
            loop = asyncio.get_running_loop()
            await asyncio.to_thread(bot.process_incoming_message, phone, name, chat_id, combined_message, loop)
        except Exception as e:
            logger.error(f"Error processing combined message for {phone}: {e}", exc_info=True)

@app.get("/")
def read_root():
    return {"status": "ok", "app": "Beerthuizen Management WhatsApp Chatbot Engine"}

@app.post("/webhook")
async def webhook_endpoint(request: Request):
    """
    Receives incoming webhook notifications from Unipile.
    Supports single JSON object or array of events.
    """
    try:
        payload = await request.json()
        logger.info(f"Raw Webhook Payload: {payload}")
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Unipile webhook payloads can be a list or a dictionary
    events = payload if isinstance(payload, list) else [payload]
    
    for event in events:
        # Check if payload is wrapped in 'body' key (e.g. n8n mocks) or is raw Unipile
        body = event.get("body") if isinstance(event, dict) and "body" in event else event
        
        if not isinstance(body, dict):
            continue
            
        # Check event type and filter out outbound agent responses
        if body.get("event") != "message_received":
            continue
        if body.get("is_sender") is True:
            # Skip messages sent by the bot/agent itself to prevent infinite loops
            continue
            
        chat_id = body.get("chat_id")
        message_text = body.get("message", "").strip()
        sender_info = body.get("sender", {})
        
        # Extract phone number and name
        attendee_specifics = sender_info.get("attendee_specifics", {})
        phone = attendee_specifics.get("phone_number")
        name = sender_info.get("attendee_name", "Valued Client")
        
        if not phone or not chat_id or not message_text:
            logger.warning(f"Incomplete event payload received: phone={phone}, chat_id={chat_id}, message_len={len(message_text)}")
            continue

        logger.info(f"Incoming message from {phone} ({name}): '{message_text}'")

        # Add message to buffer to handle rapid double/triple texting (BUG #3 Fix)
        async with buffer_lock:
            if phone in message_buffers:
                # Cancel the active timer task
                message_buffers[phone]["task"].cancel()
            else:
                message_buffers[phone] = {
                    "messages": [],
                    "name": name,
                    "chat_id": chat_id,
                    "task": None
                }
            
            message_buffers[phone]["messages"].append(message_text)
            
            # Start a new 5-second timer task
            task = asyncio.create_task(flush_buffer(phone))
            message_buffers[phone]["task"] = task

    return JSONResponse(content={"status": "event_received"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)
