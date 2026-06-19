import logging
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

logger = logging.getLogger(__name__)

PERSONAS = ["Suzanne", "Joep", "Thijs", "Lieke"]

class MongoHandler:
    def __init__(self):
        self.uri = MONGO_URI
        self.db_name = MONGO_DB_NAME
        self.collection_name = MONGO_COLLECTION
        
        try:
            self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[self.db_name]
            self.collection = self.db[self.collection_name]
            logger.info("Successfully connected to MongoDB")
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def get_conversation(self, phone: str):
        """
        Retrieves the conversation document for a phone number.
        """
        try:
            return self.collection.find_one({"phone": phone})
        except Exception as e:
            logger.error(f"Error fetching conversation: {e}")
            return None

    def create_conversation(self, phone: str, name: str, chat_id: str):
        """
        Creates a new conversation document, rotating personas.
        """
        try:
            total_conversations = self.collection.count_documents({})
            assigned_persona = PERSONAS[total_conversations % len(PERSONAS)]
            
            doc = {
                "phone": phone,
                "name": name,
                "chat_id": chat_id,
                "state": "NEW",
                "assigned_persona": assigned_persona,
                "selected_services": [],
                "current_service": None,
                "answers": {},
                "question_attempts": {},
                "messages": [],
                "asked_closing_question": False,
                "completed_services": [],
                "language": "Dutch",
                "created_at": datetime.utcnow(),
                "last_interaction": datetime.utcnow()
            }
            
            self.collection.insert_one(doc)
            logger.info(f"Created new conversation for {phone} with persona {assigned_persona}")
            return doc
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            return None

    def reset_conversation(self, phone: str):
        """
        Resets conversation state to NEW and clears selected/completed services, answers, and messages.
        """
        try:
            self.collection.update_one(
                {"phone": phone},
                {
                    "$set": {
                        "state": "NEW",
                        "selected_services": [],
                        "current_service": None,
                        "answers": {},
                        "question_attempts": {},
                        "messages": [],
                        "asked_closing_question": False,
                        "completed_services": [],
                        "last_interaction": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Reset conversation state to NEW for {phone}")
        except Exception as e:
            logger.error(f"Error resetting conversation for {phone}: {e}")

    def get_or_create_conversation(self, phone: str, name: str, chat_id: str):
        """
        Retrieves the conversation, or creates one if it doesn't exist.
        Resets conversation to NEW if the last interaction was more than 24 hours ago.
        """
        conv = self.get_conversation(phone)
        if not conv:
            conv = self.create_conversation(phone, name, chat_id)
        else:
            # Check 24 hour inactivity reset
            last_interaction = conv.get("last_interaction")
            if last_interaction:
                if isinstance(last_interaction, str):
                    try:
                        last_interaction = datetime.fromisoformat(last_interaction)
                    except ValueError:
                        last_interaction = datetime.utcnow()
                
                delta = datetime.utcnow() - last_interaction
                if delta.total_seconds() > 24 * 3600:
                    logger.info(f"Resetting conversation for {phone} due to inactivity of > 24 hours")
                    self.reset_conversation(phone)
                    conv = self.get_conversation(phone)
            
            # Update the chat_id in case it changed
            if conv.get("chat_id") != chat_id:
                self.update_conversation(phone, {"chat_id": chat_id})
                conv["chat_id"] = chat_id
        return conv

    def save_message(self, phone: str, role: str, text: str):
        """
        Saves a message to the conversation message history.
        """
        try:
            message_entry = {
                "role": role,
                "text": text,
                "timestamp": datetime.utcnow().isoformat()
            }
            self.collection.update_one(
                {"phone": phone},
                {
                    "$push": {"messages": message_entry},
                    "$set": {"last_interaction": datetime.utcnow()}
                }
            )
        except Exception as e:
            logger.error(f"Error saving message for {phone}: {e}")

    def update_conversation(self, phone: str, updates: dict):
        """
        Applies updates to a conversation document.
        """
        try:
            self.collection.update_one(
                {"phone": phone},
                {"$set": updates}
            )
        except Exception as e:
            logger.error(f"Error updating conversation for {phone}: {e}")

    def increment_question_attempt(self, phone: str, question_key: str):
        """
        Increments the counter for a specific question attempt.
        """
        try:
            self.collection.update_one(
                {"phone": phone},
                {"$inc": {f"question_attempts.{question_key}": 1}}
            )
        except Exception as e:
            logger.error(f"Error incrementing question attempt for {phone}: {e}")

    def save_service_answers(self, phone: str, service: str, answers: dict):
        """
        Saves answers under a specific service.
        """
        try:
            update_fields = {}
            for k, v in answers.items():
                if v is not None:
                    update_fields[f"answers.{service}.{k}"] = v
            
            if update_fields:
                self.collection.update_one(
                    {"phone": phone},
                    {"$set": update_fields}
                )
        except Exception as e:
            logger.error(f"Error saving answers for {phone} service {service}: {e}")
