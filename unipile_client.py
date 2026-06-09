import requests
import logging
from config import UNIPILE_API_KEY, UNIPILE_API_URL

logger = logging.getLogger(__name__)

class UnipileClient:
    def __init__(self):
        self.api_key = UNIPILE_API_KEY
        self.base_url = UNIPILE_API_URL.rstrip('/')
        
        if not self.api_key:
            logger.error("UNIPILE_API_KEY is not configured in environment variables.")

    def send_message(self, chat_id: str, text: str) -> bool:
        """
        Sends a text message to a specific Unipile Chat ID.
        """
        if not chat_id:
            logger.error("Cannot send message: chat_id is empty.")
            return False
        
        url = f"{self.base_url}/chats/{chat_id}/messages"
        headers = {
            "X-API-KEY": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "text": text
        }
        
        try:
            logger.info(f"Sending message to Unipile chat {chat_id}...")
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully sent message to Unipile chat {chat_id}")
                return True
            else:
                logger.error(f"Failed to send Unipile message. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception while sending message via Unipile: {e}")
            return False
