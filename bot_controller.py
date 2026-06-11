import logging
import asyncio
from mongo_handler import MongoHandler
from ai_agent import AIAgent, QUALIFICATION_QUESTIONS, SERVICES
from unipile_client import UnipileClient
from notification_handler import NotificationHandler
from config import CALENDLY_INTAKE_URL, CALENDLY_PHOTO_URL, CALENDLY_PODCAST_URL

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

    def process_incoming_message(self, phone: str, name: str, chat_id: str, message_text: str):
        """
        Main entry point for processing combined incoming messages from a user.
        Runs asynchronously to support timeouts and async database operations.
        """
        # 1. Fetch or create conversation
        conv = self.db.get_or_create_conversation(phone, name, chat_id)
        
        # Detect/set initial language if not set yet
        lang = conv.get("language")
        if not lang:
            dutch_words = ["ik", "wil", "huren", "opnemen", "ja", "nee", "geen", "fotoshoot", "maken", "evenement", "laten", "de", "het", "een", "en", "van", "voor", "je", "u", "we", "hallo"]
            text_lower = message_text.lower()
            dutch_count = sum(1 for word in dutch_words if f" {word} " in f" {text_lower} " or text_lower.startswith(word) or text_lower.endswith(word))
            if dutch_count > 0:
                lang = "Dutch"
            else:
                lang = "English"
            self.db.update_conversation(phone, {"language": lang})
            conv["language"] = lang
            
        persona = conv["assigned_persona"]
        state = conv["state"]
        
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
        lower_msg = message_text.lower()
        detected_services = []
        if any(keyword in lower_msg for keyword in ["podcast", "opnemen", "episode", "aflevering", "audio", "videocast"]):
            detected_services.append("podcast")
        if any(keyword in lower_msg for keyword in ["foto", "studio", "huren", "fotoshoot", "shoots", "blaricum"]):
            detected_services.append("photostudio")
        if any(keyword in lower_msg for keyword in ["website", "site", "redesign", "ontwikkeling"]):
            detected_services.append("website")
        if any(keyword in lower_msg for keyword in ["advertentie", "ads", "campagne", "adverteren"]):
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

    def _handle_menu_reply(self, conv: dict, message_text: str):
        """
        Handles replies to the welcome menu.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        clean_choice = message_text.strip()
        
        if clean_choice in MENU_OPTIONS:
            selected_service = MENU_OPTIONS[clean_choice]
            logger.info(f"User {phone} selected option {clean_choice} ({selected_service})")
            
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
            # Check if user wrote a sentence mentioning one of the services
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

        asyncio.create_task(delayed_intro())

    def _trigger_handover(self, conv: dict, services_selected: list):
        """
        Handovers conversation to manual employee (Emirhan), sends notification email.
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
        
        # Trigger email notification to Emirhan
        subject = f"Nieuwe handmatige overdracht: {name} ({phone})"
        body = (
            f"Beste Emirhan,\n\n"
            f"Een lead is overgedragen naar jou voor handmatige opvolging.\n\n"
            f"Details van de lead:\n"
            f"- Naam: {name}\n"
            f"- Telefoonnummer: {phone}\n"
            f"- Geselecteerde services: {', '.join(services_selected)}\n\n"
            f"Neem de chat handmatig over via WhatsApp / Unipile.\n\n"
            f"Met vriendelijke groet,\n"
            f"Beerthuizen Management Chatbot Engine"
        )
        self.notifier.send_email_notification(subject, body)
        logger.info(f"Handover triggered for {phone} to Emirhan")

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

        # 3. Dynamic Intent Switching (expandable requirement)
        # If the user selects a website or ads in the middle of a chat, immediately handover
        if any(item in detected_intents for item in ["website", "ads"]):
            logger.info(f"User {phone} switched intent to website/ads during qualification. Redirecting to handover.")
            self._trigger_handover(conv, list(set(selected_services + ["website", "ads"])))
            return

        # Update selected services list if new ones were detected
        updated_services = list(set(selected_services + [s for s in detected_intents if s in SERVICES]))
        if len(updated_services) > len(selected_services):
            self.db.update_conversation(phone, {"selected_services": updated_services})
            selected_services = updated_services

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
        if current_service and current_service in extracted_answers:
            self.db.save_service_answers(phone, current_service, extracted_answers[current_service])

        # 6. Question attempts counter & enforcement (BUG #5 Fix)
        # Increment attempt counter for current question
        if asking_question_key:
            self.db.increment_question_attempt(phone, asking_question_key)
            
            # Fetch updated conversation to see total attempts
            updated_conv = self.db.get_conversation(phone)
            attempts = updated_conv.get("question_attempts", {}).get(asking_question_key, 0)
            
            # If question asked more than 2 times, forcefully skip it
            if attempts >= 2:
                logger.warning(f"Question '{asking_question_key}' has been asked {attempts} times without clear answer. Forcing skip.")
                # Save 'Skipped' in MongoDB so the AI knows it's complete and won't ask it again
                answer_sub_key = asking_question_key.split('_')[-1]
                self.db.save_service_answers(phone, current_service, {answer_sub_key: "No response (Max attempts)"})

        # 7. Check if active service qualification is complete
        updated_conv = self.db.get_conversation(phone)
        is_service_complete = self._is_service_qualification_complete(updated_conv, current_service)
        
        if is_service_complete:
            logger.info(f"Service qualification for '{current_service}' completed.")
            # Add to completed list
            completed = updated_conv.get("completed_services", [])
            if current_service not in completed:
                completed.append(current_service)
                self.db.update_conversation(phone, {"completed_services": completed})
            
            # Proceed to closing question / link delivery (BUG #1 Fix)
            self._handle_closing_and_delivery(updated_conv, ai_output, message_text)
            return

        # Send regular qualification reply
        self.whatsapp.send_message(chat_id, reply)
        self.db.save_message(phone, "assistant", reply)

    def _is_service_qualification_complete(self, conv: dict, service: str) -> bool:
        """
        Validates if all qualification questions for a service have been answered.
        """
        if service not in QUALIFICATION_QUESTIONS:
            return True
            
        service_answers = conv.get("answers", {}).get(service, {})
        required_questions = QUALIFICATION_QUESTIONS[service]
        
        # Rule: Influencer Campaigns requires 1 less question (max 6 instead of 7)
        if service == "influencer":
            answered_count = sum(1 for q in required_questions if q["key"].split('_')[-1] in service_answers)
            return answered_count >= 6
            
        # Standard: Check if all questions are answered
        for q in required_questions:
            sub_key = q["key"].split('_')[-1]
            if sub_key not in service_answers:
                return False
        return True

    def _handle_closing_and_delivery(self, conv: dict, ai_output: dict, message_text: str):
        """
        Manages the transition to the closing question and booking link delivery.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        user_had_no_more_questions = ai_output.get("user_had_no_more_questions", False)
            
        # If closing question was already asked:
        lower_msg = message_text.lower()
        no_questions_keywords = ["nee", "geen", "geen vragen", "no", "no questions", "niks", "niet", "none"]
        
        if user_had_no_more_questions or any(kw in lower_msg for kw in no_questions_keywords):
            # Deliver booking links
            current_service = conv.get("current_service")
            self._send_qualified_booking_links(conv, current_service)
        else:
            # The client asked some follow up question. Send AI response
            lang = conv.get("language", "Dutch")
            reply = ai_output.get("reply", MESSAGES[lang]["closing_retry"])
            self.whatsapp.send_message(chat_id, reply)
            self.db.save_message(phone, "assistant", reply)

    def _send_qualified_booking_links(self, conv: dict, service: str = None):
        """
        Sends booking links wrapped in professional explanation templates.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        lang = conv.get("language", "Dutch")
        
        if not service:
            selected_services = conv.get("selected_services", [])
            curr = conv.get("current_service")
            if curr in selected_services:
                service = curr
            else:
                service = selected_services[0] if selected_services else "photostudio"
            
        # 1. Generate the dynamic 1-sentence summary of the user's booking details using AI
        all_answers = conv.get("answers", {})
        summary = self.ai.generate_qualification_summary([service], all_answers, lang)
        
        # Determine photostudio link dynamically
        photo_link = CALENDLY_PHOTO_URL
        photo_is_standard = True
        
        if service == "photostudio":
            photo_answers = all_answers.get("photostudio", {})
            photographer = str(photo_answers.get("photographer") or photo_answers.get("photo_photographer") or "").lower()
            extras = str(photo_answers.get("extras") or photo_answers.get("photo_extras") or "").lower()
            duration = str(photo_answers.get("duration") or photo_answers.get("photo_duration") or "").lower()
            
            negatives = ["nee", "no", "geen", "niet", "none", "skip", "not needed", "niet nodig", "n.v.t", "nvt"]
            
            # Photographer check
            need_photographer = False
            if photographer:
                if any(word in photographer for word in ["own", "alleen", "zelf", "self", "alone"]):
                    need_photographer = False
                elif any(word in photographer for word in ["photographer", "fotograaf", "yes", "ja"]):
                    need_photographer = True
                elif photographer not in negatives:
                    need_photographer = True
                    
            # Extras check
            need_extras = False
            if extras and extras not in negatives:
                need_extras = True
                
            if need_photographer or need_extras:
                photo_is_standard = False
                
            detected_duration = None
            if "2" in duration and "20" not in duration and "24" not in duration:
                detected_duration = 2
            elif "4" in duration and "40" not in duration:
                detected_duration = 4
            elif "8" in duration or "dag" in duration or "day" in duration:
                detected_duration = 8
                
            if not detected_duration:
                photo_is_standard = False
                
            if photo_is_standard:
                if detected_duration == 2:
                    photo_link = "https://calendly.com/bhmanagement/fotostudio-huren-120"
                elif detected_duration == 4:
                    photo_link = "https://calendly.com/bhmanagement/fotostudio-huren-240"
                else:
                    photo_link = "https://calendly.com/bhmanagement/fotostudio-huren-480"
            else:
                photo_link = CALENDLY_INTAKE_URL

        # Format final messages following the strict template:
        # - summary
        # - thank you message
        # - link
        
        links_sent = []
        if service == "photostudio":
            if photo_is_standard:
                if lang == "Dutch":
                    explanation = (
                        f"{summary}\n\n"
                        f"Bedankt voor uw antwoorden. U kunt direct een tijdslot voor de fotostudio reserveren via onderstaande link:\n\n"
                        f"{photo_link}"
                    )
                else:
                    explanation = (
                        f"{summary}\n\n"
                        f"Thank you for your answers. You can book a time slot directly via the link below:\n\n"
                        f"{photo_link}"
                    )
                links_sent = [photo_link]
            else:
                # Custom intake meeting
                if lang == "Dutch":
                    explanation = (
                        f"{summary}\n\n"
                        f"Bedankt voor uw antwoorden. We kunnen alle details verder bespreken tijdens een intakegesprek.\n"
                        f"U kunt via deze link een tijdslot boeken.\n"
                        f"We kijken ernaar uit om meer te horen over uw visie en deze tot leven te brengen.\n\n"
                        f"{CALENDLY_INTAKE_URL}"
                    )
                else:
                    explanation = (
                        f"{summary}\n\n"
                        f"Thank you for your answers. We can discuss all the details further during an intake meeting.\n"
                        f"You can book a time slot via this link.\n"
                        f"We look forward to hearing more about your vision and bringing it to life.\n\n"
                        f"{CALENDLY_INTAKE_URL}"
                    )
                links_sent = [CALENDLY_INTAKE_URL]
        elif service == "podcast":
            if lang == "Dutch":
                explanation = (
                    f"{summary}\n\n"
                    f"Bedankt voor uw antwoorden. U kunt direct een tijdslot boeken via onderstaande link:\n\n"
                    f"{CALENDLY_PODCAST_URL}"
                )
            else:
                explanation = (
                    f"{summary}\n\n"
                    f"Thank you for your answers. You can book a time slot directly via the link below:\n\n"
                    f"{CALENDLY_PODCAST_URL}"
                )
            links_sent = [CALENDLY_PODCAST_URL]
        else:
            # Events / Influencer / fallback to custom intake call
            if lang == "Dutch":
                explanation = (
                    f"{summary}\n\n"
                    f"Bedankt voor uw antwoorden. We kunnen alle details verder bespreken tijdens een intakegesprek.\n"
                    f"U kunt via deze link een tijdslot boeken.\n"
                    f"We kijken ernaar uit om meer te horen over uw visie en deze tot leven te brengen.\n\n"
                    f"{CALENDLY_INTAKE_URL}"
                )
            else:
                explanation = (
                    f"{summary}\n\n"
                    f"Thank you for your answers. We can discuss all the details further during an intake meeting.\n"
                    f"You can book a time slot via this link.\n"
                    f"We look forward to hearing more about your vision and bringing it to life.\n\n"
                    f"{CALENDLY_INTAKE_URL}"
                )
            links_sent = [CALENDLY_INTAKE_URL]

        self.whatsapp.send_message(chat_id, explanation)
        self.db.save_message(phone, "assistant", explanation)
        
        self.db.update_conversation(phone, {
            "state": "COMPLETED",
            "booking_links_delivered": links_sent
        })
        logger.info(f"Qualified booking links delivered contextually to {phone}")

    def _send_direct_booking_link(self, conv: dict, service: str):
        """
        Sends direct booking link immediately for Podcast/Photo Studio direct booking requests.
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        lang = conv.get("language", "Dutch")
        
        if service == "podcast":
            link = CALENDLY_PODCAST_URL
            if lang == "Dutch":
                explanation = (
                    f"Als ik het goed begrijp wil je direct een boeking maken voor de podcaststudio. "
                    f"Dat kan heel makkelijk via onderstaande link:\n\n"
                    f"{link}"
                )
            else:
                explanation = (
                    f"If I understand correctly, you want to book the podcast studio directly. "
                    f"You can do so easily via the link below:\n\n"
                    f"{link}"
                )
        else:
            link = CALENDLY_PHOTO_URL
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
        """
        phone = conv["phone"]
        chat_id = conv["chat_id"]
        persona = conv["assigned_persona"]
        
        # If user schedules via Calendly, we can trigger confirmation message
        # (This can also be invoked via a webhook from Calendly directly, but here we cover basic chat follow ups)
        ai_output = self.ai.analyze_and_reply(persona, conv, message_text)
        reply = ai_output.get("reply", "")
        
        self.whatsapp.send_message(chat_id, reply)
        self.db.save_message(phone, "assistant", reply)
