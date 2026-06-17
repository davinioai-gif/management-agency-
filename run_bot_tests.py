import sys
import os
import dotenv
import json
import asyncio

# Load environment
dotenv.load_dotenv("/home/pc/Documents/josh managment agency/.env")
sys.path.append("/home/pc/Documents/josh managment agency")

from bot_controller import BotController
from mongo_handler import MongoHandler

class BotEndToEndTester:
    def __init__(self):
        self.bot = BotController()
        self.db = MongoHandler()
        self.test_phone = "+919999999999"
        self.test_chat_id = "test_chat_end_to_end"

    def clear_db(self):
        """Reset the test user in MongoDB."""
        self.db.db[self.db.collection_name].delete_one({"phone": self.test_phone})
        print(f"\n🧹 Database cleared for test phone {self.test_phone}\n")

    async def run_dialogue(self, messages_sequence):
        """Simulate sending a sequence of messages and print bot responses."""
        for user_msg in messages_sequence:
            print(f"👤 User: {user_msg}")
            
            # We mock whatsapp.send_message to capture what the bot sends
            sent_messages = []
            def mock_send(chat_id, text):
                sent_messages.append(text)
                return True
            
            self.bot.whatsapp.send_message = mock_send
            
            # Process the message
            self.bot.process_incoming_message(
                phone=self.test_phone,
                name="Test Tester",
                chat_id=self.test_chat_id,
                message_text=user_msg
            )
            
            # Sleep to allow async tasks to execute
            if user_msg in ["1", "2", "3", "4", "5", "6"]:
                print("⏳ Waiting 6 seconds for delayed persona transfer...")
                await asyncio.sleep(6.0)
            else:
                await asyncio.sleep(0.5)
            
            # Print bot responses
            for bot_reply in sent_messages:
                print(f"🤖 Bot: {bot_reply}")
            print("-" * 50)

        # Get final DB state
        conv = self.db.get_conversation(self.test_phone)
        return conv

async def main():
    tester = BotEndToEndTester()
    
    # Run the tests
    print("=================== RUNNING PHOTO STUDIO STANDARD TEST ===================")
    tester.clear_db()
    await tester.run_dialogue(photo_studio_standard_seq)

    print("\n=================== RUNNING INFLUENCER TEST ===================")
    tester.clear_db()
    await tester.run_dialogue(influencer_seq)

    print("\n=================== RUNNING PODCAST TEST ===================")
    tester.clear_db()
    await tester.run_dialogue(podcast_seq)

    print("\n=================== RUNNING EVENTS TEST ===================")
    tester.clear_db()
    await tester.run_dialogue(events_seq)

# Define test sequences for all services
photo_studio_standard_seq = [
    "good morning",
    "2", # Rent a photo studio
    "product shoot for Waffle brand",
    "3 people",
    "4 hours",
    "no, we will rent the studio on our own",
    "no extras needed, just the studio",
    "no questions",
    "alright"
]

podcast_seq = [
    "hello",
    "1", # Record a podcast
    "interview podcast",
    "3 people",
    "both audio and video",
    "next month, no date fixed yet",
    "no editing, we do it ourselves",
    "yes, experience of 3 years",
    "do you have a parking space?", # FAQ question during qualification -> should answer and ask next question
    "no other questions",
    "nope"
]

influencer_seq = [
    "hi, influencer marketing",
    "5", # Influencer campaigns & creator matching
    "campaign to find creators and make reels",
    "cocokapse clothing brand",
    "brand promotion and high reach",
    "instagram",
    "200 dollars",
    "what type of creators do you have?", # FAQ/Clarification -> should answer and ask next question
    "micro influencers",
    "next month",
    "no questions",
    "nope"
]

events_seq = [
    "hi, events",
    "6", # Events / launches / brand trips
    "product launch",
    "brand promotion and high reach",
    "1000 guests",
    "Amsterdam",
    "under 2000$",
    "date is not decided yet", # should trigger the completion fallback
    "no questions",
    "nope"
]

if __name__ == "__main__":
    asyncio.run(main())
