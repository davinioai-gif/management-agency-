import logging
import asyncio
import json
from mongo_handler import MongoHandler
from ai_agent import AIAgent, QUALIFICATION_QUESTIONS, SERVICES
from unipile_client import UnipileClient
from notification_handler import NotificationHandler
from config import CALENDLY_INTAKE_URL, CALENDLY_PHOTO_2H_URL, CALENDLY_PHOTO_4H_URL, CALENDLY_PHOTO_8H_URL

logger = logging.getLogger(__name__)

# Menu options mapping
MENU_OPTIONS = {
    "1": "podcast",
    "2": "photostudio",
    "3": "website",
    "4": "ads",
    "5": "influencer",
    "6": "events"
}

MESSAGES = {
    "Dutch": {
        "menu_text": (
            "Hallo! Welkom bij Beerthuizen Management. Waar ben je in geïnteresseerd?\n\n"
            "1. Podcast opnemen\n"
            "2. Fotostudio huren\n"
            "3. Website laten maken\n"
            "4. Online advertenties\n"
            "5. Influencer campagnes & creator matching\n"
            "6. Evenementen / launches / brand trips\n\n"
            "Stuur het nummer van je keuze."
        ),
        "transfer_text": (
            "Bedankt voor de informatie. Ik zet je door naar een medewerker.\n"
            "We reageren meestal binnen 10 minuten."
        ),
        "intro_text": "Hi, je spreekt met {persona}. Bedankt voor je interesse in {service_label}. Waar kan ik je mee helpen?",
        "retry_text": (
            "Sorry, we hebben je keuze niet goed begrepen. "
            "Stuur a.u.b. het nummer (1 t/m 6) van de service waarin je geïnteresseerd bent."
        ),
        "closing_question": "Duidelijk, ik heb zo alle informatie genoteerd. Heb je zelf nog vragen voor mij?",
        "closing_retry": "Helder. Als er verder geen vragen zijn, stuur ik je de boekingslink door.",
        "services": {
            "podcast": "Podcast opnemen",
            "photostudio": "Fotostudio huren",
            "website": "Website laten maken",
            "ads": "Online advertenties",
            "influencer": "Influencer campagnes & creator matching",
            "events": "Evenementen / launches / brand trips"
        }
    },
    "English": {
        "menu_text": (
            "Hello! Welcome to Beerthuizen Management. What are you interested in?\n\n"
            "1. Record a podcast\n"
            "2. Rent a photo studio\n"
            "3. Have a website made\n"
            "4. Online advertisements\n"
            "5. Influencer campaigns & creator matching\n"
            "6. Events / launches / brand trips\n\n"
            "Send the number of your choice."
        ),
        "transfer_text": (
            "Thank you for the information. I am transferring you to a team member.\n"
            "We usually respond within 10 minutes."
        ),
        "intro_text": "Hi, you are speaking with {persona}. Thanks for your interest in {service_label}. How can I help you?",
        "retry_text": (
            "Sorry, we did not understand your choice. "
            "Please send the number (1 to 6) of the service you are interested in."
        ),
        "closing_question": "Clear, I have noted down all the information. Do you have any questions for me?",
        "closing_retry": "Clear. If there are no further questions, I will send you the booking link.",
        "services": {
            "podcast": "Record a podcast",
            "photostudio": "Rent a photo studio",
            "website": "Have a website made",
            "ads": "Online advertisements",
            "influencer": "Influencer campaigns & creator matching",
            "events": "Events / launches / brand trips"
        }
    }
}

class BotController:
    def __init__(self):
        self.db = MongoHandler()
        self.ai = AIAgent()
        self.whatsapp = UnipileClient()
        self.notifier = NotificationHandler()
        self.loop = None

    def process_incoming_message(self, phone: str, name: str, chat_id: str, message_text: str, loop=None):
        """
        Main entry point for processing combined incoming messages from a user.
        Runs asynchronously to support timeouts and async database operations.
        """
        self.loop = loop
        # 1. Fetch or create conversation
        conv = self.db.get_or_create_conversation(phone, name, chat_id)
        
        # Dynamically detect/set language using LLM
        lang = conv.get("language")
        detected_lang = self.ai.detect_language(message_text)
        if not lang:
            lang = detected_lang if detected_lang != "neutral" else "Dutch"
            self.db.update_conversation(phone, {"language": lang})
            conv["language"] = lang
        elif detected_lang != "neutral" and detected_lang != lang:
            lang = detected_lang
            self.db.update_conversation(phone, {"language": lang})
            conv["language"] = lang
            
        persona = conv["assigned_persona"]
        state = conv["state"]
        
        # If in HANDOVER or COMPLETED, but user asks to book a qualifying service, transition back
        if state in ("HANDOVER", "COMPLETED"):
            detected = self._detect_services_in_text(message_text)
            qual_services = [s for s in detected if s in ("podcast", "photostudio", "influencer", "events")]
            if qual_services:
                logger.info(f"User {phone} in state {state} requested a qualification service: {qual_services}. Resetting to QUALIFYING.")
                primary_service = qual_services[0]
                answers = conv.get("answers", {})
                if primary_service in answers:
                    del answers[primary_service]
                completed = conv.get("completed_services", [])
                if primary_service in completed:
                    completed = [s for s in completed if s != primary_service]
                
                existing_selected = conv.get("selected_services", [])
                updated_selected = list(set(existing_selected + qual_services))
                
                self.db.update_conversation(phone, {
                    "state": "QUALIFYING",
                    "selected_services": updated_selected,
                    "completed_services": completed,
                    "current_service": primary_service,
                    "answers": answers,
                    "asked_closing_question": False
                })
                # Re-fetch updated conversation object
                conv = self.db.get_conversation(phone)
                state = "QUALIFYING"
                
        logger.info(f"Processing message for {phone} ({name}) | State: {state} | Persona: {persona} | Msg: '{message_text}'")
        
        # Save user message to history
        self.db.save_message(phone, "user", message_text)
        
        # Update local conversation representation
        conv = self.db.get_conversation(phone)
        
        # 2. State machine routing
        if state == "NEW":
            self._handle_new_user(conv, message_text)
            
        elif state == "MENU_SENT":
            self._handle_menu_reply(conv, message_text)
            
        elif state == "QUALIFYING":
            self._handle_qualification_chat(conv, message_text)
            
        elif state == "HANDOVER":
            # If in handover (manual takeover), bot only answers FAQ queries but does not qualify or send booking links.
            self._handle_handover_chat(conv, message_text)
            
        elif state == "COMPLETED":
            # Post-booking follow ups
            self._handle_completed_chat(conv, message_text)
            
        else:
            logger.warning(f"Unknown state '{state}' for user {phone}. Resetting to menu.")
            self._send_menu_message(conv)

    def _send_menu_message(self, conv: dict):
        """
        Sends the standard welcome menu.
        """
        lang = conv.get("language", "Dutch")
        menu_text = MESSAGES[lang]["menu_text"]
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        
        self.whatsapp.send_message(chat_id, menu_text)
        self.db.save_message(phone, "assistant", menu_text)
        self.db.update_conversation(phone, {"state": "MENU_SENT"})
        logger.info(f"Menu sent to {phone}")

    def _detect_services_in_text(self, message_text: str) -> list:
        """
        Keyword-based service detection. Used ONLY for website/ads handover reliability.
        For other services, the AI's detected_intents is the primary signal.
        Keywords must be specific enough to avoid false positives mid-conversation.
        """
        lower_msg = message_text.lower()
        detected_services = []
        if any(keyword in lower_msg for keyword in ["podcast", "opnemen", "episode", "aflevering", "videocast"]):
            detected_services.append("podcast")
        # Use specific photostudio keywords — 'studio' alone is too generic (e.g. 'je studio verhuurt')
        if any(keyword in lower_msg for keyword in ["photostudio", "fotostudio", "fotoshoot", "foto studio", "shoots", "blaricum", "photo studio"]):
            detected_services.append("photostudio")
        if any(keyword in lower_msg for keyword in ["website", "site", "redesign", "ontwikkeling"]):
            detected_services.append("website")
        if any(keyword in lower_msg for keyword in ["advertentie", "ads", "adverteren"]):
            detected_services.append("ads")
        if any(keyword in lower_msg for keyword in ["influencer", "creator", "matching", "creators"]):
            detected_services.append("influencer")
        if any(keyword in lower_msg for keyword in ["event", "launches", "brand trip", "evenement"]):
            detected_services.append("events")
        return detected_services

    def _handle_new_user(self, conv: dict, message_text: str):
        """
        Handles brand new conversations. Checks for direct intent or displays menu.
        """
        phone = conv["phone"]
        
        # Check if user directly mentions services to skip the menu
        detected_services = self._detect_services_in_text(message_text)
        
        if detected_services:
            logger.info(f"Direct intent detected for {phone}: {detected_services}")
            # If Website or Ads is in the mix, trigger direct human handover
            if "website" in detected_services or "ads" in detected_services:
                self._trigger_handover(conv, detected_services)
            else:
                # Direct transfer to persona
                primary_service = detected_services[0]
                self.db.update_conversation(phone, {
                    "selected_services": detected_services,
                    "current_service": primary_service
                })
                # Re-fetch updated conversation object
                conv = self.db.get_conversation(phone)
                self._transfer_to_persona(conv, primary_service)
        else:
            self._send_menu_message(conv)

    def _detect_menu_option(self, message_text: str) -> str:
        """
        Attempts to detect a menu option (1 to 6) or its word equivalent
        in a user's response. Returns the matched option string ("1"-"6") or None.
        """
        lower_msg = message_text.lower().strip()
        
        # 1. Exact match digits or option keys
        if lower_msg in ["1", "2", "3", "4", "5", "6"]:
            return lower_msg
            
        # 2. Check for standalone digits or words
        cleaned = lower_msg
        for char in ".,!?()[]{}":
            cleaned = cleaned.replace(char, " ")
        words = cleaned.split()
        
        # Note: We exclude "een" as it is the Dutch article "a/an" and causes false positives.
        digit_map = {
            "1": "1", "one": "1", "één": "1",
            "2": "2", "two": "2", "twee": "2",
            "3": "3", "three": "3", "drie": "3",
            "4": "4", "four": "4", "vier": "4",
            "5": "5", "five": "5", "vijf": "5",
            "6": "6", "six": "6", "zes": "6"
        }
        
        # Single word option choice
        if len(words) == 1 and words[0] in digit_map:
            return digit_map[words[0]]
            
        # Multiple words: only match if digits/words are accompanied by indicators or part of a very short selection sentence
        option_indicators = ["option", "optie", "number", "nummer", "keuze", "choice", "kies", "choose"]
        for i, word in enumerate(words):
            if word in digit_map:
                if word in ["1", "2", "3", "4", "5", "6"]:
                    if i > 0 and words[i-1] in option_indicators:
                        return digit_map[word]
                    if len(words) <= 3:
                        return digit_map[word]
                else:
                    if i > 0 and words[i-1] in option_indicators:
                        return digit_map[word]
                    
        return None

    def _handle_menu_reply(self, conv: dict, message_text: str):
        """
        Handles replies to the welcome menu.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        
        # 1. First prioritize direct keyword service detection
        detected_services = self._detect_services_in_text(message_text)
        if detected_services:
            logger.info(f"Direct intent detected in menu reply for {phone}: {detected_services}")
            if "website" in detected_services or "ads" in detected_services:
                self._trigger_handover(conv, detected_services)
            else:
                primary_service = detected_services[0]
                self.db.update_conversation(phone, {
                    "selected_services": detected_services,
                    "current_service": primary_service
                })
                conv = self.db.get_conversation(phone)
                self._transfer_to_persona(conv, primary_service)
            return

        # 2. Otherwise fall back to detecting menu option numbers/words
        selected_option = self._detect_menu_option(message_text)
        if selected_option:
            selected_service = MENU_OPTIONS[selected_option]
            logger.info(f"User {phone} selected option {selected_option} ({selected_service})")
            
            if selected_service in ["website", "ads"]:
                self._trigger_handover(conv, [selected_service])
            else:
                self.db.update_conversation(phone, {
                    "selected_services": [selected_service],
                    "current_service": selected_service
                })
                conv = self.db.get_conversation(phone)
                self._transfer_to_persona(conv, selected_service)
        else:
            # Invalid selection retry
            lang = conv.get("language", "Dutch")
            retry_text = MESSAGES[lang]["retry_text"]
            self.whatsapp.send_message(chat_id, retry_text)
            self.db.save_message(phone, "assistant", retry_text)

    def _transfer_to_persona(self, conv: dict, service: str):
        """
        Simulates human transfer (10min delay message + Wait + Persona Introduction).
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        persona = conv["assigned_persona"]
        lang = conv.get("language", "Dutch")
        
        # 1. 10min Handoff message
        transfer_text = MESSAGES[lang]["transfer_text"]
        self.whatsapp.send_message(chat_id, transfer_text)
        self.db.save_message(phone, "assistant", transfer_text)
        
        # 2. Wait 5 seconds to simulate transfer (non-blocking async sleep)
        async def delayed_intro():
            await asyncio.sleep(5)
            service_label = MESSAGES[lang]["services"].get(service, service)
            intro_template = MESSAGES[lang]["intro_text"]
            intro_text = intro_template.format(persona=persona, service_label=service_label)
            self.whatsapp.send_message(chat_id, intro_text)
            self.db.save_message(phone, "assistant", intro_text)
            self.db.update_conversation(phone, {"state": "QUALIFYING"})
            logger.info(f"Persona intro sent for {phone} ({persona})")

        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(delayed_intro(), self.loop)
        else:
            asyncio.create_task(delayed_intro())

    def _trigger_handover(self, conv: dict, services_selected: list, user_message: str = ""):
        """
        Handovers conversation to manual employee (Emirhan), sends notification email + n8n webhook.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        name = conv["name"]
        
        # Send handover message
        lang = conv.get("language", "Dutch")
        handoff_text = MESSAGES[lang]["transfer_text"]
        self.whatsapp.send_message(chat_id, handoff_text)
        self.db.save_message(phone, "assistant", handoff_text)
        
        # Update database state to HANDOVER
        self.db.update_conversation(phone, {
            "state": "HANDOVER",
            "selected_services": services_selected,
            "current_service": services_selected[0] if services_selected else None
        })
        
        # Trigger n8n webhook — include actual user message for better context
        webhook_msg = user_message.strip() if user_message.strip() else \
            f"Client {name} ({phone}) requested manual handover for services: {', '.join(services_selected)}."
        self.notifier.send_n8n_handover_webhook(name, phone, webhook_msg, services_selected)
        
        logger.info(f"Handover triggered for {phone} to Emirhan and n8n webhook")

    def _handle_qualification_chat(self, conv: dict, message_text: str):
        """
        Runs the conversational qualification flow using the OpenAI LLM.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        persona = conv["assigned_persona"]
        current_service = conv.get("current_service")
        selected_services = conv.get("selected_services", [])
        
        # Safeguard: Check direct booking requests for Podcast/Photo Studio (Direct Book path)
        lower_msg = message_text.lower()
        if current_service in ["podcast", "photostudio"]:
            if any(phrase in lower_msg for phrase in ["ik wil boeken", "boeking maken", "direct boeken", "tijdslot boeken", "boeken"]):
                logger.info(f"Direct booking request detected for {phone} on service {current_service}")
                self._send_direct_booking_link(conv, current_service)
                return

        # 1. Run AI Agent analysis
        ai_output = self.ai.analyze_and_reply(persona, conv, message_text)
        
        # 2. Extract state parameters from AI JSON response
        detected_intents = ai_output.get("detected_intents", [])
        extracted_answers = ai_output.get("extracted_answers", {})
        is_negative_response = ai_output.get("is_negative_response", False)
        user_had_no_more_questions = ai_output.get("user_had_no_more_questions", False)
        reply = ai_output.get("reply", "")
        asking_question_key = ai_output.get("asking_question_key")

        logger.info(f"AI Output: intents={detected_intents}, asking_key={asking_question_key}, is_neg={is_negative_response}, closing_no={user_had_no_more_questions}")

        # 3. Dynamic Intent Switching
        # For handover services (website/ads), we ONLY switch mid-qualification if explicitly detected via robust keyword matching
        # to avoid false positive digit matches (like "4 in totaal" triggering "ads" handover).
        keyword_detected = self._detect_services_in_text(message_text)
        
        # If website or ads detected via keyword at any point → trigger handover immediately
        if any(item in keyword_detected for item in ["website", "ads"]):
            logger.info(f"User {phone} switched intent to website/ads during qualification. Redirecting to handover.")
            all_services = list(set(selected_services + [s for s in keyword_detected if s in ["website", "ads"]]))
            self._trigger_handover(conv, all_services, message_text)
            return

        # Check if bot cannot answer the query
        if ai_output.get("cannot_answer", False):
            booking_links_delivered = conv.get("booking_links_delivered", [])
            lang = conv.get("language", "Dutch")
            if booking_links_delivered:
                if lang == "Dutch":
                    reminder = "Ik heb je de boekingslink al gestuurd. Je kunt op die link klikken om een tijdslot te reserveren en je vraag te stellen, dan bespreken we alles daar."
                else:
                    reminder = "I have already sent you the booking link. You can click on that link to book a slot and raise your query, and we will discuss everything there."
                self.whatsapp.send_message(chat_id, reminder)
                self.db.save_message(phone, "assistant", reminder)
                logger.info(f"Cannot-answer in Qualifying: Link already sent to {phone}. Sent reminder.")
                return
            else:
                logger.info(f"Cannot-answer in Qualifying: Link not yet sent to {phone}. Triggering booking link delivery.")
                self._send_qualified_booking_links(conv, current_service)
                return

        # Update selected_services AND current_service ONLY based on AI-detected intents.
        # We only allow switching to qualifying services (podcast, photostudio, influencer, events)
        # to prevent manual handover services (website, ads) from being set as the active qualifying service.
        # Keyword detection is intentionally NOT used here to avoid false positives.
        new_qualifying = [s for s in detected_intents if s in ["podcast", "photostudio", "influencer", "events"] and s not in selected_services]
        if new_qualifying:
            updated_services = list(set(selected_services + new_qualifying))
            new_primary = new_qualifying[0]
            logger.info(f"User {phone} added new AI-detected service '{new_primary}'. Updating current_service and selected_services in DB.")
            self.db.update_conversation(phone, {
                "selected_services": updated_services,
                "current_service": new_primary,
                "asked_closing_question": False
            })
            selected_services = updated_services
            current_service = new_primary

        # 4. Handle Negative / Skip Answer (BUG #4 Fix)
        # If user explicitly declined to answer (e.g. 'no/nee/not needed'), mark the active question as 'Skipped'
        last_asked_key = conv.get("question_attempts", {})
        if is_negative_response and last_asked_key:
            # Find the most recently incremented/asked question key
            active_keys = [k for k in last_asked_key.keys()]
            if active_keys:
                last_key = active_keys[-1]
                logger.info(f"Negative answer detected. Automatically skipping question: {last_key}")
                self.db.save_service_answers(phone, current_service, {last_key.split('_')[-1]: "Skipped / Not needed"})

        # 5. Save Extracted Answers to database
        if current_service:
            # Handle both nested (e.g. {"podcast": {...}}) and flat (e.g. {"type": "..."}) AI extracted answers
            answers_to_save = {}
            if current_service in extracted_answers:
                answers_to_save = extracted_answers[current_service]
            else:
                # Top level keys excluding known service names
                for k, v in extracted_answers.items():
                    if k not in SERVICES:
                        answers_to_save[k] = v
            
            if answers_to_save and isinstance(answers_to_save, dict):
                cleaned_answers = {}
                for k, v in answers_to_save.items():
                    sub_key = k.split('_')[-1]
                    cleaned_answers[sub_key] = v
                self.db.save_service_answers(phone, current_service, cleaned_answers)

        # 6. Question attempts counter & enforcement (BUG #5 Fix)
        # Increment attempt counter for current question
        if asking_question_key:
            normalized_key = asking_question_key.split('_')[-1]
            self.db.increment_question_attempt(phone, normalized_key)
            
            # Fetch updated conversation to see total attempts
            updated_conv = self.db.get_conversation(phone)
            attempts = updated_conv.get("question_attempts", {}).get(normalized_key, 0)
            
            # If question asked more than 2 times, forcefully skip it
            if attempts >= 2:
                logger.warning(f"Question '{normalized_key}' has been asked {attempts} times without clear answer. Forcing skip.")
                # Save 'Skipped' in MongoDB so the AI knows it's complete and won't ask it again
                self.db.save_service_answers(phone, current_service, {normalized_key: "No response (Max attempts)"})

        # 7. CRITICAL: If closing question was already asked → go directly to closing handler.
        # Do NOT re-run _is_service_qualification_complete — user is past that stage.
        updated_conv = self.db.get_conversation(phone)
        if updated_conv.get("asked_closing_question", False):
            logger.info(f"Closing question already asked for {phone}. Routing directly to closing/delivery handler.")
            self._handle_closing_and_delivery(updated_conv, ai_output, message_text)
            return

        # 8. Check if all qualification questions are answered
        is_service_complete = self._is_service_qualification_complete(updated_conv, current_service)
        ai_initiated_closing = bool(asking_question_key and asking_question_key.endswith("questions"))
        
        if is_service_complete or ai_initiated_closing:
            logger.info(f"Service qualification for '{current_service}' completed (AI initiated closing: {ai_initiated_closing}).")
            completed = updated_conv.get("completed_services", [])
            if current_service not in completed:
                completed.append(current_service)
                self.db.update_conversation(phone, {"completed_services": completed})
            
            # Re-fetch updated conv to ensure any updates are captured
            updated_conv = self.db.get_conversation(phone)
            self._handle_closing_and_delivery(updated_conv, ai_output, message_text)
            return

        # Send regular qualification reply
        self.whatsapp.send_message(chat_id, reply)
        self.db.save_message(phone, "assistant", reply)

    def _is_service_qualification_complete(self, conv: dict, service: str) -> bool:
        """
        Checks if all REAL qualification questions are answered.
        IMPORTANT: The *_questions key (closing 'any questions?') is EXCLUDED here
        because it is handled by the asked_closing_question / _handle_closing_and_delivery flow.
        """
        if service not in QUALIFICATION_QUESTIONS:
            return True
            
        service_answers = conv.get("answers", {}).get(service, {})
        
        # Only check real qualification questions — exclude the closing 'questions' key
        required_questions = [
            q for q in QUALIFICATION_QUESTIONS[service]
            if q["key"].split('_')[-1] != "questions"
        ]
        
        # All services: every question must be present in the answers database
        for q in required_questions:
            key_suffix = q["key"].split('_')[-1]
            if key_suffix not in service_answers:
                return False
        return True

    def _handle_closing_and_delivery(self, conv: dict, ai_output: dict, message_text: str):
        """
        Strict 2-step gate for closing:
        Step 1: If closing question hasn't been asked yet → ask it and mark asked_closing_question=True.
        Step 2: If closing question WAS already asked → check user's reply and send link or answer FAQ.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        lang = conv.get("language", "Dutch")
        asked_closing_question = conv.get("asked_closing_question", False)

        if not asked_closing_question:
            # STEP 1: Ask the closing question — use the AI's reply if it contains one,
            # otherwise fall back to a default closing message.
            closing_reply = ai_output.get("reply", "")
            # Ensure the reply is actually the closing question and not something else
            closing_keywords = ["question", "vragen", "vraag", "anything else", "nog iets", "help you"]
            is_closing_reply = any(kw in closing_reply.lower() for kw in closing_keywords)
            
            if not closing_reply or not is_closing_reply:
                if lang == "Dutch":
                    closing_reply = "Heeft u nog vragen voor mij?"
                else:
                    closing_reply = "Do you have any questions for me?"
            
            self.whatsapp.send_message(chat_id, closing_reply)
            self.db.save_message(phone, "assistant", closing_reply)
            self.db.update_conversation(phone, {"asked_closing_question": True})
            return

        # STEP 2: Closing question was already asked — now evaluate user's reply
        user_had_no_more_questions = ai_output.get("user_had_no_more_questions", False)
        is_negative_response = ai_output.get("is_negative_response", False)

        # Clean the message text for robust word-by-word keyword checking
        cleaned_msg = message_text.lower().strip()
        for char in ".,!?()[]{}":
            cleaned_msg = cleaned_msg.replace(char, " ")
        words = cleaned_msg.split()

        no_questions_keywords = [
            "nee", "geen", "geen vragen", "no", "no questions", "niks", "niet", "none",
            "nope", "nothing", "clear", "thanks", "bedankt", "dank", "sure", "perfect",
            "alright", "not at this point", "that's it", "thats it", "not really",
            "nou goed dan", "is goed", "top", "prima", "oke", "okay", "ok", "goed",
            "super", "helder", "duidelijk", "geen dank", "dankje", "dank u",
            "bedankt voor de informatie", "thanks voor de informatie", "got it",
            "fine", "great", "awesome", "sounds good", "thank you"
        ]

        keyword_matched = False
        for kw in no_questions_keywords:
            kw_clean = kw.lower().strip()
            if " " in kw_clean:
                # Phrase match with padded spaces for word boundaries
                padded_msg = " " + " ".join(words) + " "
                padded_kw = " " + kw_clean + " "
                if padded_kw in padded_msg:
                    keyword_matched = True
                    break
            else:
                # Single word exact match
                if kw_clean in words:
                    keyword_matched = True
                    break

        has_no_questions = (
            user_had_no_more_questions or
            is_negative_response or
            keyword_matched
        )

        logger.info(f"Closing phase evaluation for {phone}: user_had_no_more_questions={user_had_no_more_questions}, is_negative_response={is_negative_response}, keyword_matched={keyword_matched} -> has_no_questions={has_no_questions}")

        if has_no_questions:
            # Deliver the booking link
            current_service = conv.get("current_service")
            self._send_qualified_booking_links(conv, current_service)
        else:
            # User asked a real follow-up question — answer it and wait for next reply
            reply = ai_output.get("reply", "")
            if reply:
                self.whatsapp.send_message(chat_id, reply)
                self.db.save_message(phone, "assistant", reply)
            # Keep asked_closing_question=True so next reply still routes here

    def _send_qualified_booking_links(self, conv: dict, service: str = None):
        """
        Sends the booking link for the completed service.
        Each service gets its own link. The intake link is sent only once — if it was
        already delivered in this conversation, it will not be resent.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        lang = conv.get("language", "Dutch")
        selected_services = conv.get("selected_services", [])
        
        if not service:
            curr = conv.get("current_service")
            if curr in selected_services:
                service = curr
            else:
                service = selected_services[0] if selected_services else "photostudio"
        
        # 1. Generate a FULL summary covering all services the user has discussed
        all_answers = conv.get("answers", {})
        
        # Include all services with answers for a complete summary
        services_for_summary = [s for s in selected_services if s in all_answers] or [service]
        
        # Track which services have already had their links delivered
        delivered_links = conv.get("booking_links_delivered", [])
        intake_already_sent = CALENDLY_INTAKE_URL in delivered_links
        
        summary = self.ai.generate_qualification_summary(services_for_summary, all_answers, lang)
        
        # 2. Determine which link to send
        # RULE: Only photostudio has specific hour-based direct links.
        # Podcast, events, influencer → always intake link.
        links_sent = []
        
        if service == "photostudio":
            photo_answers = all_answers.get("photostudio", {})
            photographer = str(photo_answers.get("photographer") or photo_answers.get("photo_photographer") or "").lower()
            extras = str(photo_answers.get("extras") or photo_answers.get("photo_extras") or "").lower()
            duration = str(photo_answers.get("duration") or photo_answers.get("photo_duration") or "").lower()
            
            def has_keyword(text: str, keywords: list) -> bool:
                if not text:
                    return False
                text_clean = f" {text.lower().strip()} "
                for char in ".,!?()[]{}":
                    text_clean = text_clean.replace(char, " ")
                text_clean = " ".join(text_clean.split())
                text_clean = f" {text_clean} "
                
                for kw in keywords:
                    if f" {kw.lower().strip()} " in text_clean:
                        return True
                return False

            # Photographer: standard = NO photographer
            need_photographer = bool(photographer) and has_keyword(
                photographer, ["photographer", "fotograaf", "yes", "ja", "need", "graag"]
            ) and not has_keyword(
                photographer, ["no", "nee", "niet", "without", "zonder", "not", "own", "zelf", "alone"]
            )
            
            # Extras: standard = NO extras
            need_extras = bool(extras) and has_keyword(
                extras, ["yes", "ja", "lighting", "backdrop", "assistance", "editing", "service", "setup", "prop"]
            ) and not has_keyword(
                extras, ["no", "nee", "niet", "nothing", "niks", "geen", "none", "thanks", "bedankt"]
            )
            
            # Duration detection
            # RULE: ONLY exactly 2h, 4h or 8h → direct booking link.
            # Anything else (1 day, 5 days, 10 hours, etc.) → intake call.
            detected_duration = None
            if "day" not in duration and "dag" not in duration:
                if "2" in duration and "20" not in duration and "24" not in duration:
                    detected_duration = 2
                elif "4" in duration and "40" not in duration:
                    detected_duration = 4
                elif "8" in duration:
                    detected_duration = 8
            # Any mention of "day/dag" OR anything not matching 2/4/8 → detected_duration stays None → intake
            
            is_standard = not need_photographer and not need_extras and detected_duration is not None
            
            if is_standard:
                if detected_duration == 2:
                    photo_link = CALENDLY_PHOTO_2H_URL
                elif detected_duration == 4:
                    photo_link = CALENDLY_PHOTO_4H_URL
                else:
                    photo_link = CALENDLY_PHOTO_8H_URL
                
                if lang == "Dutch":
                    explanation = (
                        f"{summary}\n\n"
                        f"Bedankt voor uw antwoorden. U kunt direct een tijdslot voor de fotostudio reserveren via onderstaande link:\n\n"
                        f"{photo_link}"
                    )
                else:
                    explanation = (
                        f"{summary}\n\n"
                        f"Thank you for your answers. You can book a time slot for the photo studio directly via the link below:\n\n"
                        f"{photo_link}"
                    )
                links_sent = [photo_link]
            else:
                # Photostudio with photographer/extras or unknown duration → intake
                if not intake_already_sent:
                    if lang == "Dutch":
                        explanation = (
                            f"{summary}\n\n"
                            f"Bedankt voor uw antwoorden. Omdat u aanvullende wensen heeft, bespreken we de details graag in een intakegesprek.\n"
                            f"U kunt via deze link een tijdslot boeken:\n\n"
                            f"{CALENDLY_INTAKE_URL}"
                        )
                    else:
                        explanation = (
                            f"{summary}\n\n"
                            f"Thank you for your answers. Since you have some specific requirements, we'd love to discuss the details in an intake call.\n"
                            f"You can book a time slot via this link:\n\n"
                            f"{CALENDLY_INTAKE_URL}"
                        )
                    links_sent = [CALENDLY_INTAKE_URL]
                else:
                    logger.info(f"Intake link already delivered to {phone}. Skipping resend for photostudio.")
                    if lang == "Dutch":
                        reminder = "Bedankt! U kunt de eerder verzonden intake link gebruiken om contact met ons op te nemen."
                    else:
                        reminder = "Thank you! Please use the intake link we sent earlier to contact us."
                    self.whatsapp.send_message(chat_id, reminder)
                    self.db.save_message(phone, "assistant", reminder)
                    self._mark_service_completed(phone, conv, service)
                    return
        else:
            # Podcast / Events / Influencer → always intake link (only once)
            if intake_already_sent:
                logger.info(f"Intake link already delivered to {phone}. Skipping resend for service '{service}'.")
                if lang == "Dutch":
                    reminder = "Bedankt! U kunt de eerder verzonden intake link gebruiken om contact met ons op te nemen."
                else:
                    reminder = "Thank you! Please use the intake link we sent earlier to contact us."
                self.whatsapp.send_message(chat_id, reminder)
                self.db.save_message(phone, "assistant", reminder)
                self._mark_service_completed(phone, conv, service)
                return
            
            if lang == "Dutch":
                explanation = (
                    f"{summary}\n\n"
                    f"Bedankt voor uw antwoorden. We kunnen alle details verder bespreken tijdens een intakegesprek.\n"
                    f"U kunt via deze link een tijdslot boeken:\n\n"
                    f"{CALENDLY_INTAKE_URL}"
                )
            else:
                explanation = (
                    f"{summary}\n\n"
                    f"Thank you for your answers. We would love to discuss all the details during an intake call.\n"
                    f"You can book a time slot via this link:\n\n"
                    f"{CALENDLY_INTAKE_URL}"
                )
            links_sent = [CALENDLY_INTAKE_URL]

        self.whatsapp.send_message(chat_id, explanation)
        self.db.save_message(phone, "assistant", explanation)
        
        updated_links = list(set(delivered_links + links_sent))
        completed_services = conv.get("completed_services", [])
        if service not in completed_services:
            completed_services.append(service)
        
        self.db.update_conversation(phone, {
            "state": "COMPLETED",
            "booking_links_delivered": updated_links,
            "completed_services": completed_services,
            "asked_closing_question": False
        })
        logger.info(f"Booking link for '{service}' delivered to {phone}")

    def _mark_service_completed(self, phone: str, conv: dict, service: str):
        """Helper to mark a service as completed without sending a duplicate link."""
        completed_services = conv.get("completed_services", [])
        if service not in completed_services:
            completed_services.append(service)
        self.db.update_conversation(phone, {
            "state": "COMPLETED",
            "completed_services": completed_services,
            "asked_closing_question": False
        })

    def _send_direct_booking_link(self, conv: dict, service: str):
        """
        Sends direct booking link immediately for Photo Studio direct booking requests.
        Podcast and all other services redirect to intake call.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        lang = conv.get("language", "Dutch")
        
        # Only photostudio has a direct link — all others use intake
        link = CALENDLY_INTAKE_URL
        if lang == "Dutch":
            explanation = (
                f"Als ik het goed begrijp wil je direct de fotostudio in Blaricum boeken. "
                f"Dat kan heel makkelijk via onderstaande link:\n\n"
                f"{link}"
            )
        else:
            explanation = (
                f"If I understand correctly, you want to book the photo studio in Blaricum directly. "
                f"You can do so easily via the link below:\n\n"
                f"{link}"
            )

        self.whatsapp.send_message(chat_id, explanation)
        self.db.save_message(phone, "assistant", explanation)
        self.db.update_conversation(phone, {
            "state": "COMPLETED",
            "booking_links_delivered": [link]
        })
        logger.info(f"Direct booking link sent to {phone} for {service}")

    def _handle_handover_chat(self, conv: dict, message_text: str):
        """
        Handles post-handoff questions using FAQ data only, without asking qualification questions.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        persona = conv["assigned_persona"]
        
        # Run AI in strict FAQ answering mode
        ai_output = self.ai.analyze_and_reply(persona, conv, message_text)
        reply = ai_output.get("reply", "")
        
        self.whatsapp.send_message(chat_id, reply)
        self.db.save_message(phone, "assistant", reply)

    def _handle_completed_chat(self, conv: dict, message_text: str):
        """
        Handles follow-up messages after the booking/intake link has been sent.
        - Short acknowledgements are silently ignored.
        - If the AI cannot answer the user's question, send the intake link (only once).
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        persona = conv["assigned_persona"]
        lang = conv.get("language", "Dutch")
        
        # Ignore short acknowledgements that don't need a reply
        acknowledgements = ["ok", "okay", "thanks", "thank you", "bedankt", "dank", "sure", "great", "perfect", "alright", "got it", "👍"]
        lower_msg = message_text.lower().strip()
        if lower_msg in acknowledgements or len(lower_msg) <= 4:
            logger.info(f"Ignoring short acknowledgement from {phone}: '{message_text}'")
            return
        
        ai_output = self.ai.analyze_and_reply(persona, conv, message_text)
        reply = ai_output.get("reply", "")
        cannot_answer = ai_output.get("cannot_answer", False)
        
        # If AI cannot answer → send intake link (only if not already sent)
        if cannot_answer:
            delivered_links = conv.get("booking_links_delivered", [])
            has_sent_link = bool(delivered_links)
            
            if not has_sent_link:
                if lang == "Dutch":
                    intake_msg = (
                        f"Voor verdere vragen kun je contact opnemen via onderstaande link:\n\n"
                        f"{CALENDLY_INTAKE_URL}"
                    )
                else:
                    intake_msg = (
                        f"For any further queries, you can reach us directly via the link below:\n\n"
                        f"{CALENDLY_INTAKE_URL}"
                    )
                self.whatsapp.send_message(chat_id, intake_msg)
                self.db.save_message(phone, "assistant", intake_msg)
                # Track that intake link has now been delivered
                updated_links = list(set(delivered_links + [CALENDLY_INTAKE_URL]))
                self.db.update_conversation(phone, {"booking_links_delivered": updated_links})
                logger.info(f"Cannot-answer: Sent intake link to {phone} for unanswerable query.")
            else:
                # Link already sent — just remind them
                if lang == "Dutch":
                    reminder = "Ik heb je de boekingslink al gestuurd. Je kunt op die link klikken om een tijdslot te reserveren en je vraag te stellen, dan bespreken we alles daar."
                else:
                    reminder = "I have already sent you the booking link. You can click on that link to book a slot and raise your query, and we will discuss everything there."
                self.whatsapp.send_message(chat_id, reminder)
                self.db.save_message(phone, "assistant", reminder)
                logger.info(f"Cannot-answer: Link already sent to {phone}. Sent reminder.")
            return
        
        if reply:
            self.whatsapp.send_message(chat_id, reply)
            self.db.save_message(phone, "assistant", reply)
