import unittest
from unittest.mock import MagicMock, patch
import json
import asyncio

# Setup dummy environment variables for testing
import os
os.environ["MONGO_URI"] = "mongodb://localhost:27017"
os.environ["MONGO_DB_NAME"] = "testDB"
os.environ["OPENAI_API_KEY"] = "mock_key"
os.environ["UNIPILE_API_KEY"] = "mock_key"

# Now we can import our modules
from bot_controller import BotController
from mongo_handler import MongoHandler
from ai_agent import AIAgent
from unipile_client import UnipileClient
from notification_handler import NotificationHandler

class TestBotController(unittest.TestCase):
    def setUp(self):
        # Patch external network clients
        self.mongo_patcher = patch('mongo_handler.MongoClient')
        self.mock_mongo_client = self.mongo_patcher.start()
        
        self.openai_patcher = patch('ai_agent.OpenAI')
        self.mock_openai_client = self.openai_patcher.start()
        
        self.unipile_patcher = patch('unipile_client.requests.post')
        self.mock_unipile_post = self.unipile_patcher.start()
        
        self.email_patcher = patch('notification_handler.smtplib.SMTP')
        self.mock_smtp = self.email_patcher.start()
        
        # Instantiate controller
        self.controller = BotController()
        
        # Setup mock database response helpers
        self.mock_conv_doc = {
            "phone": "+31648689297",
            "name": "AJ",
            "chat_id": "chat_id_123",
            "state": "QUALIFYING",
            "assigned_persona": "Suzanne",
            "selected_services": ["podcast"],
            "current_service": "podcast",
            "answers": {},
            "question_attempts": {},
            "messages": [],
            "asked_closing_question": False,
            "completed_services": []
        }
        self.controller.db.get_or_create_conversation = MagicMock(return_value=self.mock_conv_doc)
        self.controller.db.get_conversation = MagicMock(return_value=self.mock_conv_doc)
        self.controller.db.update_conversation = MagicMock()
        self.controller.db.save_message = MagicMock()
        self.controller.db.save_service_answers = MagicMock()
        self.controller.db.increment_question_attempt = MagicMock()

    def tearDown(self):
        self.mongo_patcher.stop()
        self.openai_patcher.stop()
        self.unipile_patcher.stop()
        self.email_patcher.stop()

    def test_bug1_closing_question_timing(self):
        """
        Verify that 'Do you have any more questions?' is NOT asked until all service qualification questions are complete.
        """
        # Case A: Qualification incomplete (e.g. format missing)
        self.mock_conv_doc["answers"] = {"podcast": {"people": "3"}} # format is missing
        self.mock_conv_doc["asked_closing_question"] = False
        
        # We check qualification complete directly
        is_complete = self.controller._is_service_qualification_complete(self.mock_conv_doc, "podcast")
        self.assertFalse(is_complete)
        
        # Case B: All answers populated
        self.mock_conv_doc["answers"] = {
            "podcast": {
                "format": "serie",
                "type": "interview",
                "people": "3",
                "media": "video+audio",
                "date": "next month",
                "editing": "yes",
                "experience": "first time",
                "questions": "no"
            }
        }
        is_complete = self.controller._is_service_qualification_complete(self.mock_conv_doc, "podcast")
        self.assertTrue(is_complete)

    def test_bug2_booking_link_context(self):
        """
        Verify that booking links are never sent alone and always wrapped in contextual template strings.
        """
        self.controller.whatsapp.send_message = MagicMock()
        self.mock_conv_doc["selected_services"] = ["podcast"]
        self.mock_conv_doc["language"] = "Dutch"
        
        self.controller._send_qualified_booking_links(self.mock_conv_doc)
        
        # Check that the sent message contains both the link and explanatory context
        args, _ = self.controller.whatsapp.send_message.call_args
        sent_text = args[1]
        
        self.assertIn("Bedankt voor uw antwoorden", sent_text)
        self.assertIn("https://calendly.com/bhmanagement/podcast-opnemen", sent_text)

    def test_bug4_negative_answer_skip(self):
        """
        Verify that a negative response ('no', 'nee') results in skipping the current question.
        """
        # Mocking AI response specifying a negative response
        mock_ai_reply = {
            "detected_intents": ["podcast"],
            "extracted_answers": {},
            "is_negative_response": True,
            "user_had_no_more_questions": False,
            "reply": "Oké, geen probleem.",
            "asking_question_key": "podcast_format"
        }
        self.controller.ai.analyze_and_reply = MagicMock(return_value=mock_ai_reply)
        self.mock_conv_doc["question_attempts"] = {"podcast_format": 1}
        self.controller.db.get_conversation.return_value = {
            **self.mock_conv_doc,
            "question_attempts": {"podcast_format": 1}
        }
        
        self.controller._handle_qualification_chat(self.mock_conv_doc, "Nee, liever niet.")
        
        # Verify that save_service_answers was called with 'Skipped' value
        self.controller.db.save_service_answers.assert_any_call(
            "+31648689297", "podcast", {"format": "Skipped / Not needed"}
        )

    def test_bug5_question_repetition_limit(self):
        """
        Verify that if a question is asked more than twice without an answer, it is skipped.
        """
        # Mock AI output asking the same question again
        mock_ai_reply = {
            "detected_intents": ["podcast"],
            "extracted_answers": {},
            "is_negative_response": False,
            "user_had_no_more_questions": False,
            "reply": "Hoeveel episodes wil je opnemen?",
            "asking_question_key": "podcast_format"
        }
        self.controller.ai.analyze_and_reply = MagicMock(return_value=mock_ai_reply)
        self.mock_conv_doc["question_attempts"] = {"podcast_format": 2}
        
        # Mock conversation state indicating the question has already been asked twice
        self.controller.db.get_conversation.return_value = {
            **self.mock_conv_doc,
            "question_attempts": {"podcast_format": 2} # Asked twice already
        }
        
        self.controller._handle_qualification_chat(self.mock_conv_doc, "unrelated answer")
        
        # Verify that code automatically overrides and marks the answer as 'No response'
        self.controller.db.save_service_answers.assert_any_call(
            "+31648689297", "podcast", {"format": "No response (Max attempts)"}
        )

    def test_bug3_message_buffering(self):
        """
        Verify that multiple messages sent in quick succession are buffered and processed as one.
        """
        import app
        from app import webhook_endpoint
        
        # Mock Request object
        class MockRequest:
            def __init__(self, json_data):
                self._json = json_data
            async def json(self):
                return self._json

        # Mock bot controller's process method
        mock_process = MagicMock()
        app.bot.process_incoming_message = mock_process
        
        # Webhook payload template
        payload_template = {
            "body": {
                "event": "message_received",
                "chat_id": "chat_id_123",
                "message": "default",
                "is_sender": False,
                "sender": {
                    "attendee_specifics": {
                        "phone_number": "+31648689297"
                    },
                    "attendee_name": "AJ"
                }
            }
        }
        
        async def run_buffer_test():
            # Trigger 3 quick webhooks
            payloads = [
                {**payload_template, "body": {**payload_template["body"], "message": "First message"}},
                {**payload_template, "body": {**payload_template["body"], "message": "Second message"}},
                {**payload_template, "body": {**payload_template["body"], "message": "Third message"}},
            ]
            
            for p in payloads:
                await webhook_endpoint(MockRequest(p))
                
            # Verify that they are currently in the buffer
            self.assertIn("+31648689297", app.message_buffers)
            self.assertEqual(len(app.message_buffers["+31648689297"]["messages"]), 3)
            
            # Wait for the flush_buffer timer
            with patch('app.asyncio.sleep', return_value=None):
                await app.flush_buffer("+31648689297")
            
            # Verify process_incoming_message was called exactly once with combined string
            mock_process.assert_called_once_with(
                "+31648689297", "AJ", "chat_id_123", "First message Second message Third message"
            )

        asyncio.run(run_buffer_test())

    def test_photo_studio_standard_links(self):
        """
        Verify that standard photo studio requests (no photographer/stylist) return hour-specific links.
        """
        self.controller.whatsapp.send_message = MagicMock()
        
        # Test 2 hours
        self.mock_conv_doc["selected_services"] = ["photostudio"]
        self.mock_conv_doc["answers"] = {
            "photostudio": {
                "photo_duration": "2 uur",
                "photo_extras": "nee"
            }
        }
        self.controller._send_qualified_booking_links(self.mock_conv_doc)
        args, _ = self.controller.whatsapp.send_message.call_args
        self.assertIn("https://calendly.com/bhmanagement/fotostudio-huren-120", args[1])
        
        # Test 4 hours
        self.controller.whatsapp.send_message.reset_mock()
        self.mock_conv_doc["answers"]["photostudio"]["photo_duration"] = "4 hours"
        self.controller._send_qualified_booking_links(self.mock_conv_doc)
        args, _ = self.controller.whatsapp.send_message.call_args
        self.assertIn("https://calendly.com/bhmanagement/fotostudio-huren-240", args[1])
        
        # Test 8 hours
        self.controller.whatsapp.send_message.reset_mock()
        self.mock_conv_doc["answers"]["photostudio"]["photo_duration"] = "8 uur"
        self.controller._send_qualified_booking_links(self.mock_conv_doc)
        args, _ = self.controller.whatsapp.send_message.call_args
        self.assertIn("https://calendly.com/bhmanagement/fotostudio-huren-480", args[1])

    def test_photo_studio_custom_links(self):
        """
        Verify that custom photo studio requests (with photographer or stylist or invalid duration) return the intake link.
        """
        self.controller.whatsapp.send_message = MagicMock()
        self.mock_conv_doc["selected_services"] = ["photostudio"]
        
        # Photographer requested
        self.mock_conv_doc["answers"] = {
            "photostudio": {
                "photo_duration": "4 uur",
                "photo_extras": "ja, we willen een fotograaf"
            }
        }
        self.controller._send_qualified_booking_links(self.mock_conv_doc)
        args, _ = self.controller.whatsapp.send_message.call_args
        self.assertIn("https://calendly.com/bhmanagement/intake-call-beerthuizen-management", args[1])
        
        # Custom duration (e.g. 5 hours)
        self.controller.whatsapp.send_message.reset_mock()
        self.mock_conv_doc["answers"] = {
            "photostudio": {
                "photo_duration": "5 uur",
                "photo_extras": "nee"
            }
        }
        self.controller._send_qualified_booking_links(self.mock_conv_doc)
        args, _ = self.controller.whatsapp.send_message.call_args
        self.assertIn("https://calendly.com/bhmanagement/intake-call-beerthuizen-management", args[1])

    def test_menu_sentence_intent_bypass(self):
        """
        Verify that if the user replies to the menu with a sentence containing service keywords (e.g., 'i want to book your photostudio'),
        the bot correctly detects the intent and initiates the service qualification process.
        """
        self.controller.whatsapp.send_message = MagicMock()
        self.controller._transfer_to_persona = MagicMock()
        self.controller.ai.analyze_and_reply = MagicMock(return_value={
            "detected_intents": ["photostudio"],
            "extracted_answers": {},
            "is_negative_response": False,
            "user_had_no_more_questions": False,
            "reply": "Hi, je spreekt met Lieke. Bedankt voor je interesse in onze fotostudio. Hoelang wil je de studio boeken?",
            "asking_question_key": "photo_duration"
        })
        self.controller.db.get_conversation.return_value = {
            **self.mock_conv_doc,
            "state": "QUALIFYING",
            "selected_services": ["photostudio"],
            "current_service": "photostudio"
        }
        
        self.controller._handle_menu_reply(self.mock_conv_doc, "i want to book your photostudio")
        
        # Verify conversation updated with selected services
        self.controller.db.update_conversation.assert_called_with(
            "+31648689297", {
                "selected_services": ["photostudio"],
                "current_service": "photostudio"
            }
        )
        self.controller._transfer_to_persona.assert_called_once()

    def test_language_persistence(self):
        """
        Verify that language is initially detected (Dutch vs English) and locked.
        """
        self.controller._transfer_to_persona = MagicMock()
        
        # Case A: Dutch keywords
        self.controller.db.get_or_create_conversation = MagicMock(return_value={"assigned_persona": "Suzanne", "state": "NEW", "phone": "+31648689297", "chat_id": "chat_id_123", "name": "AJ"})
        self.controller.db.get_conversation = MagicMock(return_value={"assigned_persona": "Suzanne", "state": "NEW", "phone": "+31648689297", "chat_id": "chat_id_123", "name": "AJ", "language": "Dutch"})
        self.controller.db.update_conversation = MagicMock()
        
        self.controller.process_incoming_message("+31648689297", "AJ", "chat_id_123", "ik wil graag een fotoshoot boeken")
        self.controller.db.update_conversation.assert_any_call("+31648689297", {"language": "Dutch"})
        
        # Case B: English input
        self.controller.db.update_conversation.reset_mock()
        self.controller.db.get_or_create_conversation = MagicMock(return_value={"assigned_persona": "Suzanne", "state": "NEW", "phone": "+31648689297", "chat_id": "chat_id_123", "name": "AJ"})
        self.controller.db.get_conversation = MagicMock(return_value={"assigned_persona": "Suzanne", "state": "NEW", "phone": "+31648689297", "chat_id": "chat_id_123", "name": "AJ", "language": "English"})
        
        self.controller.process_incoming_message("+31648689297", "AJ", "chat_id_123", "I want to book a photo shoot please")
        self.controller.db.update_conversation.assert_any_call("+31648689297", {"language": "English"})

if __name__ == '__main__':
    unittest.main()
