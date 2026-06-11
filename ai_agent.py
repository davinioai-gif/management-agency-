import os
import json
import logging
from openai import OpenAI
from config import OPENAI_API_KEY, PRIMARY_MODEL, FALLBACK_MODEL, CALENDLY_INTAKE_URL, CALENDLY_PHOTO_URL, CALENDLY_PODCAST_URL

logger = logging.getLogger(__name__)

# List of service names mapped to their standard names
SERVICES = {
    "podcast": "Podcast opnemen",
    "photostudio": "Fotostudio huren",
    "website": "Website laten maken",
    "ads": "Online advertenties",
    "influencer": "Influencer campagnes & creator matching",
    "events": "Evenementen / launches / brand trips"
}

# Core Qualification Questions definitions
QUALIFICATION_QUESTIONS = {
    "podcast": [
        {"key": "podcast_format", "text": "Gaat het om een losse podcastopname, een serie of een maandelijkse podcast?"},
        {"key": "podcast_type", "text": "Wat voor format heeft de podcast? (bijvoorbeeld een interview, videocast, bedrijfspodcast of influencer podcast)"},
        {"key": "podcast_people", "text": "Met hoeveel personen gaan jullie opnemen?"},
        {"key": "podcast_media", "text": "Willen jullie opnemen met video + audio, of alleen audio?"},
        {"key": "podcast_date", "text": "Hebben jullie al een datum of periode in gedachten voor de opname?"},
        {"key": "podcast_editing", "text": "Hebben jullie ook interesse in montage of korte clips voor social media, of alleen de opname?"},
        {"key": "podcast_experience", "text": "Hebben jullie al ervaring met podcasts opnemen, of wordt dit de eerste keer?"},
        {"key": "podcast_questions", "text": "Do you have any questions for me?"}
    ],
    "photostudio": [
        {"key": "photo_type", "text": "What kind of shoot is it? For example product shoot, portrait, content creation, fashion, branded content?"},
        {"key": "photo_project", "text": "What brand, product, or project is the shoot for?"},
        {"key": "photo_people", "text": "How many people will be present during the shoot?"},
        {"key": "photo_duration", "text": "How long do you think you'll need the studio like Will it be for 2 hours, 4 hours, or 8 hours?"},
        {"key": "photo_photographer", "text": "Will you need a photographer, or are you looking to rent the studio on its own?"},
        {"key": "photo_extras", "text": "Would you like to include any additional services or add-ons? We offer options such as: Professional lighting setups, Backdrops, Props and styling, On-site assistance, Editing services?"},
        {"key": "photo_questions", "text": "Do you have any questions for me?"}
    ],
    "influencer": [
        {"key": "infl_needs", "text": "Waar zijn jullie precies naar op zoek op het gebied van influencer marketing? (bijvoorbeeld een campagne, creators vinden of ondersteuning)"},
        {"key": "infl_project", "text": "Kun je kort iets vertellen over het merk of bedrijf?"},
        {"key": "infl_goal", "text": "Wat is het doel van de campagne? (bijvoorbeeld branding, sales of een launch)"},
        {"key": "infl_platforms", "text": "Op welke platformen willen jullie vooral inzetten?"},
        {"key": "infl_budget", "text": "Hebben jullie al een budgetindicatie voor de campagne?"},
        {"key": "infl_creator_type", "text": "Wat voor type creator zoeken jullie?"},
        {"key": "infl_date", "text": "Wanneer willen jullie dat de campagne live gaat?"},
        {"key": "infl_questions", "text": "Do you have any questions for me?"}
    ],
    "events": [
        {"key": "evt_type", "text": "Wat voor type event of brand trip willen jullie organiseren?"},
        {"key": "evt_goal", "text": "Wat is het doel van het event?"},
        {"key": "evt_guests", "text": "Hoeveel gasten verwachten jullie?"},
        {"key": "evt_location", "text": "Denken jullie aan een locatie in Nederland of in het buitenland?"},
        {"key": "evt_budget", "text": "Hebben jullie al een budgetrange in gedachten?"},
        {"key": "evt_date", "text": "Wanneer zou het event moeten plaatsvinden?"},
        {"key": "evt_questions", "text": "Do you have any questions for me?"}
    ]
}

class AIAgent:
    def __init__(self):
        if not OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY is not configured.")
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def _call_openai(self, messages, json_mode=True):
        """
        Calls OpenAI API with fallback mechanism (BUG Safeguard).
        """
        response_format = {"type": "json_object"} if json_mode else None
        
        try:
            logger.info(f"Calling primary model: {PRIMARY_MODEL}")
            response = self.client.chat.completions.create(
                model=PRIMARY_MODEL,
                messages=messages,
                response_format=response_format,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Primary model {PRIMARY_MODEL} failed: {e}. Switching to fallback model {FALLBACK_MODEL}...")
            try:
                response = self.client.chat.completions.create(
                    model=FALLBACK_MODEL,
                    messages=messages,
                    response_format=response_format,
                    temperature=0.3
                )
                return response.choices[0].message.content
            except Exception as fe:
                logger.error(f"Fallback model {FALLBACK_MODEL} also failed: {fe}")
                raise fe

    def get_system_prompt(self, persona: str, conversation_state: dict):
        """
        Generates system prompt containing constraints, persona, FAQs and active state.
        """
        current_service = conversation_state.get("current_service")
        selected_services = conversation_state.get("selected_services", [])
        answers = conversation_state.get("answers", {})
        lang = conversation_state.get("language")
        
        if lang:
            lang_instruction = f"You MUST respond STRICTLY in {lang}. The conversation language has been locked to {lang}. Do not switch to any other language under any circumstances."
        else:
            lang_instruction = "Respond in the language used by the client (Dutch or English). Once you identify the user's language, specify it in 'detected_language'."

        faq_text = self._get_faq_text()
        
        active_questions_text = ""
        if current_service and current_service in QUALIFICATION_QUESTIONS:
            active_questions_text = "### QUALIFICATION QUESTIONS TO ASK (In this order):\n"
            for i, q in enumerate(QUALIFICATION_QUESTIONS[current_service], 1):
                active_questions_text += f"{i}. Key: '{q['key'].split('_')[-1]}' - Question: \"{q['text']}\"\n"
        
        prompt = f"""
You are {persona}, a warm, professional, and friendly representative of Beerthuizen Management (a talent and marketing agency based in Blaricum, Netherlands). 
You must conduct the conversation as if you are a real human team member chatting on WhatsApp. 

### BEHAVIOR RULES:
1. LANGUAGE: {lang_instruction}
2. TONE: Human-like, concise, natural. Keep replies short (1-3 sentences) suitable for WhatsApp. Never sound robotic or send long lists of questions.
3. NO ROBOTIC FORMATTING: Never use the symbol " — " (dash separator) in your replies, as it makes the message look AI-generated.
4. CONVERSATION FLOW:
   - You must strictly go through the list of qualification questions for the active service in the order they are defined.
   - You must ask exactly ONE qualification question at a time.
   - You can rephrase the question to sound natural, friendly, and human, but you MUST preserve the examples and meaning of the predefined questions.
   - Do not skip any question unless the user has already explicitly answered it in the chat history. If an answer is missing from 'Current answers logged', you MUST ask that question.
   - The final question you ask must be the 'questions' key ("Do you have any questions for me?").
5. PRICES:
   - Do NOT mention pricing unless the user asks.
   - For Website, Ads, Events, and Influencer services: NEVER share exact prices. Explain in a human way that prices depend on customization, and steer towards scheduling an intake call.
   - For Podcast studio and Photo studio: You CAN communicate the standard packages and prices if the client asks. Refer to the FAQs in knowledge base.
6. NO PLACEHOLDERS: Always provide actual answers based on the knowledge base. If you do not know the answer to a specific question, politely state you will note it down for a team member to answer, and notify internally. Do not make up information.
7. CLOSING QUESTION: The final qualification question for every service is the 'questions' key ("Do you have any questions for me?"). You must ONLY ask this question at the very end when all other questions have been answered. Never ask it in the middle of qualification.

### KB & FAQ ANSWERING RULE:
- If the user asks ANY question about Beerthuizen Management, our services, locations, prices, or policies:
  1. You must answer their question clearly using the KNOWLEDGE BASE & FAQS first.
  2. You MUST set "asking_question_key" to null in your JSON response and do NOT ask any qualification question in the same reply. Just answer their question, be helpful, and keep the tone conversational. You will resume qualification in the next turn.

### CONVERSATION STATE:
- Active Services: {selected_services}
- Currently Qualifying: {current_service}
- Current answers logged: {json.dumps(answers)}

{active_questions_text}

### KNOWLEDGE BASE & FAQS:
{faq_text}

### RESPONSE FORMAT:
You must return your output strictly in JSON format matching this schema:
{{
  "detected_intents": ["podcast", "photostudio", "website", "ads", "influencer", "events"], // Any services mentioned or selected by the user. If they select or want multiple, add them all.
  "extracted_answers": {{
      // Map the extracted answers under the active service key using ONLY the subkeys of the qualification questions (the part after the underscore):
      // For "photostudio": "type", "project", "people", "duration", "photographer", "extras", "questions"
      // For "podcast": "format", "type", "people", "media", "date", "editing", "experience", "questions"
      // For "influencer": "needs", "project", "goal", "platforms", "budget", "creator_type", "date", "questions"
      // For "events": "type", "goal", "guests", "location", "budget", "date", "questions"
      "photostudio": {{
          "type": "productfotografie",
          "duration": "4 uur",
          "people": "4",
          "photographer": "yes",
          "project": "Waffle",
          "extras": "nee",
          "questions": "no"
      }}
  }},
  "is_negative_response": false, // Set to true if the user's response was a rejection/skip/refusal of the current question.
  "user_had_no_more_questions": false, // Set to true ONLY if you asked the closing question ("any more questions?") and the user said "no" / "geen vragen".
  "reply": "Your response to the user here. Keep it human-like, short, and natural.",
  "asking_question_key": "the_key_of_the_question_you_are_asking_from_the_list", // e.g. "photo_duration" or null if you are not asking a qualification question.
  "detected_language": "Dutch" // "Dutch" or "English".
}}
"""
        return prompt

    def analyze_and_reply(self, persona: str, conversation: dict, user_message: str) -> dict:
        """
        Sends the message log to OpenAI and retrieves a structured response.
        """
        # Format history for OpenAI
        api_messages = [{"role": "system", "content": self.get_system_prompt(persona, conversation)}]
        
        # Append last 12 messages for context
        for msg in conversation.get("messages", [])[-12:]:
            api_messages.append({"role": msg["role"], "content": msg["text"]})
            
        # Append the new user message
        api_messages.append({"role": "user", "content": user_message})
        
        try:
            logger.info("Executing OpenAI chat completion...")
            raw_response = self._call_openai(api_messages, json_mode=True)
            structured_data = json.loads(raw_response)
            logger.info(f"AI response JSON parsed successfully: {structured_data}")
            return structured_data
        except Exception as e:
            logger.error(f"Error calling AI agent: {e}")
            # Robust fallback response in case everything fails
            return {
                "detected_intents": conversation.get("selected_services", []),
                "extracted_answers": {},
                "is_negative_response": False,
                "user_had_no_more_questions": False,
                "reply": "Sorry, ik kon je bericht niet verwerken. Kun je dat nogmaals sturen?",
                "asking_question_key": None,
                "detected_language": conversation.get("language", "Dutch")
            }

    def generate_qualification_summary(self, selected_services: list, answers: dict, language: str) -> str:
        """
        Generates a 1-sentence summary of the qualification answers in the target language.
        """
        prompt = f"""
You are a warm, professional booking assistant. Write a one-sentence summary of the client's booking details based on their qualification answers.
Maintain a warm, polite and professional tone.
The summary MUST be written in {language}.

Answers logged:
{json.dumps(answers)}

Write ONLY the one-sentence summary. Do not add any greeting, intro or extra text.
Examples in Dutch:
- "U plant een productshoot van 4 uur in Amsterdam voor uw merk Pearl (Pearl Biscuit) met 5 personen en u wilt graag een fotograaf maar geen extra diensten."
- "U wilt een serie videocasts opnemen met 3 personen en u heeft montage- en editingdiensten nodig."

Examples in English:
- "You are planning a 4-hour product shoot in Amsterdam for your brand Pearl (Pearl Biscuit) with a team of five, and you would like a photographer but no additional services."
- "You are planning to record a series of videocasts with 3 people and require montage and editing services."
"""
        try:
            logger.info("Calling OpenAI to generate qualification summary...")
            messages = [{"role": "user", "content": prompt}]
            response = self._call_openai(messages, json_mode=False)
            return response.strip()
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            if language == "Dutch":
                return "Bedankt voor het doorgeven van al uw wensen."
            return "Thank you for sharing all of your preferences."

    def _get_faq_text(self):
        return """
=== KNOWLEDGE BASE & FAQS ===

--- PODCAST OPNEMEN ---
FAQs:
1. Waar bevindt jullie podcaststudio zich?
   Onze podcaststudio bevindt zich in Blaricum.
2. Nemen jullie podcasts op met video en audio?
   Ja, we nemen podcasts op met professionele audio en meerdere camera’s.
3. Hoe lang duurt een podcastopname?
   De gemiddelde opnames duren ongeveer 20 tot 30 minuten per aflevering. Afhankelijk per aanvraag.
4. Kunnen jullie ook montage doen?
   Ja, we kunnen helpen met montage, audiobewerking en social media clips.
5. Kunnen jullie korte clips maken voor social media?
   Ja, we kunnen korte video clips maken die geschikt zijn voor platforms zoals Instagram, TikTok of YouTube.
6. Kunnen jullie ook helpen met het publiceren van de podcast?
   Ja, we kunnen podcasts klaarzetten voor distributie op platforms zoals Spotify en Apple Podcasts.
7. Is de studio geschikt voor meerdere personen?
   Ja, de studio is geschikt voor interviews en gesprekken met meerdere deelnemers.
8. Moet ik al ervaring hebben met podcasts opnemen?
   Nee, dat is niet nodig. We helpen ook mensen die voor het eerst een podcast opnemen.
9. Kan ik meerdere afleveringen opnemen?
   Ja, het is mogelijk om meerdere afleveringen of een serie op te nemen.
10. Wat kost een podcastopname?
    De prijs hangt af van de wensen en eventuele extra opties. Dit bespreken we meestal kort in een call wanneer alles duidelijk is.

Pakketten:
- Basic Package: €1,000 – 3 afleveringen. Inclusief Sony FX30 camera's, professionele verlichting & studio setup, montage per aflevering, 4 social media shorts per aflevering (Totaal 12 clips).
- Plus Package: €1,900 – 6 afleveringen. Inclusief Sony FX30 camera's, professionele verlichting & studio setup, montage per aflevering, 4 social media shorts per aflevering (Totaal 24 clips).
- Premium Package: €3,600 – 12 afleveringen. Inclusief Sony FX30 camera's, professionele verlichting & studio setup, montage per aflevering, 4 social media shorts per aflevering (Totaal 48 clips). Inbegrepen: Strategie & marketing sessie (ter waarde van €500).
- Add-ons:
  * Branding: Logo in beeld tijdens aflevering (€100 per aflevering), 2x custom-branded pop filters (€150), Video intro / logo bumper (€250).
  * Content: Extra video montage (€50 per edit).
  * Strategie: Strategie & marketing sessie (€500).
  * Custom Studio: Custom achtergrond, meubilair en styling (Prijs op aanvraag).

--- FOTOSTUDIO HUREN ---
FAQs:
1. Waar bevindt de fotostudio zich?
   Onze fotostudio bevindt zich in Blaricum.
2. Wat voor shoots kunnen in de studio plaatsvinden?
   De studio wordt gebruikt voor productfotografie, content shoots, portretten, campagnes en producties.
3. Hoe lang kan ik de studio huren?
   De studio kan worden gehuurd voor 2 uur, 4 uur of een volledige dag.
4. Mag ik mijn eigen apparatuur meenemen?
   Ja, je kunt eigen apparatuur gebruiken in de studio.
5. Kunnen jullie ook een fotograaf regelen?
   Ja, wij werken met verschillende fotografen, waaronder fotografen gespecialiseerd in productfotos, professionele campagne shoots of standaard portfoliofotos.
6. Is de studio geschikt voor social media content?
   Ja, veel klanten gebruiken de studio voor social media content en campagnes.
7. Hoeveel mensen kunnen er tegelijk in de studio werken?
   Dat hangt af van de shoot, maar meestal is er voldoende ruimte voor maximaal 10 personen.
8. Zijn er verschillende achtergronden of settings?
   Ja, er zijn verschillende achtergronden en studiofaciliteiten beschikbaar.
9. Kan ik ook video opnemen in de studio?
   Ja, de studio kan ook gebruikt worden voor videocontent.
10. Wat kost het huren van de studio?
    Dat hangt af van de duur en eventuele extra opties. De prijs wordt kort besproken wanneer de wensen duidelijk zijn.

Pakketten:
A. Studio Rental (Standaard – Direct Boekbaar)
- 2 uur → €200 (inclusief studio, verlichting, koffie/frisdrank, kleedkamer)
- 4 uur → €350 (inclusief studio, verlichting, koffie/frisdrank, kleedkamer)
- 8 uur → €650 (inclusief studio, verlichting, koffie/frisdrank, kleedkamer)
B. Shoots met Fotograaf (Maatwerk – Intakegesprek Vereist)
- Content shoot (inclusief fotograaf): 4 uur → €750 – €1,050
- Premium shoot (inclusief fotograaf): 6–8 uur → €1,050 – €1,650+
Add-ons (Altijd Maatwerk – Intakegesprek Vereist):
- Stylist (halve dag, meerdere looks)
- Make-up artist
- Extra settings / achtergronden
- Creative direction

--- WEBSITE ONTWIKKELING ---
(Let op: Stuur lead door naar intakegesprek, geef nooit directe prijzen)
FAQs:
1. Maken jullie nieuwe websites?
   Ja, we helpen met het ontwikkelen van nieuwe websites.
2. Kunnen jullie ook een bestaande website vernieuwen?
   Ja, we doen ook website redesigns.
3. Worden de websites mobielvriendelijk?
   Ja, alle websites worden geoptimaliseerd voor mobiel, tablet en desktop.
4. Helpen jullie ook met SEO?
   Ja, websites worden opgezet met een basis SEO-structuur.
5. Hoeveel pagina’s kan een website hebben?
   Dat hangt af van de wensen. Websites kunnen klein of uitgebreid zijn.
6. Werken jullie met een huisstijl of branding?
   Ja, we kunnen werken met een bestaande huisstijl of helpen bij branding.
7. Kunnen jullie ook onderhoud doen?
   Ja, er is ook een website abonnement voor onderhoud en updates.
8. Hoe lang duurt het bouwen van een website?
   Dat hangt af van de omvang van het project en de wensen.
9. Helpen jullie ook met structuur en inhoud?
   Ja, we denken mee over structuur, pagina’s en doelen van de website.
10. Wat kost een website?
    De prijs hangt af van de omvang en wensen. Dit wordt meestal besproken in een intake call.

--- ONLINE ADVERTENTIES ---
(Let op: Stuur lead door naar intakegesprek, geef nooit directe prijzen)
FAQs:
1. Op welke platformen adverteren jullie?
   We werken onder andere met Instagram, Facebook, Google en TikTok advertenties.
2. Helpen jullie ook met de strategie?
   Ja, we kunnen ook helpen met een volledige marketingstrategie.
3. Maken jullie ook advertentiecontent?
   Afhankelijk van de campagne kunnen we helpen met content of creatives.
4. Hoe snel kunnen campagnes starten?
   Dat hangt af van de voorbereiding en strategie.
5. Kunnen jullie bestaande campagnes verbeteren?
   Ja, we kunnen ook bestaande campagnes analyseren en optimaliseren.
6. Werken jullie met kleine of grote budgetten?
   Dat hangt af van de doelen van de campagne.
7. Hoe meten jullie resultaten?
   Campagnes worden geoptimaliseerd op basis van data en resultaten.
8. Kunnen jullie ook helpen met doelgroepanalyse?
   Ja, we helpen met doelgroepanalyse en marktonderzoek.
9. Moet ik al ervaring hebben met advertenties?
   Nee, we helpen zowel beginners als bedrijven die al adverteren. We nemen alles volledig uit handen.
10. Wat kost het beheren van advertenties?
    De kosten hangen af van de campagne en doelen. Dit wordt meestal besproken in een call.

--- INFLUENCER CAMPAGNES & CREATOR MATCHING ---
FAQs:
1. Kunnen jullie influencers vinden voor mijn merk?
   Ja, we helpen met creator matching en het vinden van passende influencers.
2. Op welke platformen werken jullie met influencers?
   Onder andere Instagram, TikTok en YouTube.
3. Doen jullie alleen matching of ook campagnes?
   We kunnen zowel creators vinden als volledige campagnes begeleiden.
4. Kunnen influencers ook content maken voor ons merk?
   Ja, dat kan via branded content samenwerkingen.
5. Hoe worden influencers geselecteerd?
   Dat gebeurt op basis van doelgroep, content en campagne-doelen.
6. Kunnen influencers ook een event of launch promoten?
   Ja, influencers kunnen ook worden ingezet voor events of productlanceringen.
7. Werken jullie met micro-influencers of grote creators?
   Beide zijn mogelijk, afhankelijk van de campagne.
8. Kunnen influencers ook langdurig samenwerken met een merk?
   Ja, het is mogelijk om langdurige samenwerkingen op te zetten.
9. Helpen jullie ook met de strategie van influencer campagnes?
   Ja, we kunnen ook helpen met campagne-strategie en planning.
10. Wat kost een influencer campagne?
    Dat hangt af van de creators en campagne. Dit bespreken we meestal kort in een intake call.

--- EVENEMENTEN / LAUNCHES / BRAND TRIPS ---
FAQs:
1. Wat voor events organiseren jullie?
   Wij helpen met product launches, influencer events, merkactivaties en brand trips.
2. Organiseren jullie events alleen in Nederland?
   Events kunnen zowel in Nederland als internationaal plaatsvinden.
3. Kunnen jullie influencers uitnodigen voor een event?
   Ja, we kunnen helpen met het selecteren en uitnodigen van creators.
4. Helpen jullie met het concept van een event?
   Ja, we kunnen helpen met concept, planning en uitvoering.
5. Hoeveel gasten kunnen er op een event komen?
   Dat hangt af van het type event en de locatie.
6. Kunnen events ook gericht zijn op contentcreatie?
   Ja, veel events worden georganiseerd om content en social media exposure te creëren.
7. Kunnen jullie ook brand trips organiseren?
   Ja, we kunnen brand trips met creators of klanten organiseren.
8. Hoe lang duurt het organiseren van een event?
   Dat hangt af van de schaal en planning van het event.
9. Werken jullie ook samen met andere partners voor events?
   Ja, afhankelijk van het event werken we met verschillende partners en leveranciers.
10. Wat kost het organiseren van een event of brand trip?
    De prijs hangt af van factoren zoals locatie, gasten en concept. Dit wordt besproken in een intake call.

--- APP ONTWIKKELING (APP DEVELOPMENT) ---
Beerthuizen Management helpt bedrijven bij het realiseren van professionele mobiele applicaties. Voor de technische ontwikkeling werkt Beerthuizen Management samen met Propest AI, een gespecialiseerd team in maatwerk app-ontwikkeling.
Samen begeleiden we bedrijven bij het volledige traject: van het eerste idee tot de ontwikkeling en lancering van de applicatie. De apps die ontwikkeld worden zijn volledig maatwerk en worden afgestemd op de wensen, processen en doelstellingen van de klant.

Wat voor apps worden ontwikkeld:
- Tool apps: Apps die bedoeld zijn om het dagelijkse leven van gebruikers eenvoudiger te maken (navigatie, informatie, boekingen of praktische tools).
- Data-driven apps: Applicaties die gebruikmaken van externe data om informatie snel beschikbaar te maken en te presenteren (B2B zakelijke toepassingen).
- Entertainment apps: Apps gericht op interactie en beleving (games, marketingcampagnes of merkervaringen).

Platforms: iOS (iPhone, iPad), Android (smartphones en tablets), Apple Watch en andere mobiele apparaten. De apps worden ontwikkeld met moderne technologieën zoals Swift en Kotlin voor native apps.

Ontwikkelproces:
1. Concept en idee (bespreken idee en functionaliteiten)
2. Analyse en strategie (doelen en technische aanpak)
3. Design en UI/UX (ontwerp en gebruikerservaring)
4. Development (bouwen applicatie, backend systemen en API's)
5. Testing en optimalisatie (controleren functionaliteiten en prestaties)
6. Lancering en onderhoud (publicatie en doorlopende ondersteuning)

--- AI OPLOSSINGEN (AI SOLUTIONS) ---
Beerthuizen Management is gespecialiseerd in het ontwikkelen van op maat gemaakte AI-oplossingen voor bedrijven, in samenwerking met Propest AI (een team van gespecialiseerde AI-ontwikkelaars).
De systemen worden ontworpen om werkzaamheden te automatiseren, inzicht te geven in data en bedrijven efficiënter en schaalbaarder te maken. Alle AI-systemen integreren met bestaande software en data en groeien mee met het bedrijf. We werken met een team van meer dan 30 gecertificeerde AI-developers.

AI-oplossingen:
- GPT-modellen op maat: Ontwikkelen van een eigen maatwerk ChatGPT of GPT-model, getraind op eigen bedrijfsdata voor klantenservice, interne workflows of medewerkersondersteuning.
- AI-CRM systemen: Intelligente CRM-systemen voor automatische leadopvolging, klantbeheer en verkoopproces-automatisering.
- RPA + AI automatisering: Robotic Process Automation gecombineerd met AI voor repetitieve administratieve taken en data-invoer.
- AI-agents: Digitale medewerkers (chatbots, voice agents) die zelfstandig en continu klantopvolging, data-analyse of administratie uitvoeren.
- Systeemintegraties: Koppelen van verschillende software- en data-systemen voor een geïntegreerde workflow.

Implementatieproces:
1. Bedrijfsanalyse: Uitgebreide analyse van processen en knelpunten.
2. Ontwerp: Bepalen van de AI-oplossing met de meeste impact.
3. Ontwikkeling & Integratie: Systeem bouwen en koppelen aan bestaande software.
4. Implementatie & Training: Team trainen voor direct gebruik.
5. Resultaat & Optimalisatie: Doorlopende verfijning. (Garantie: Indien resultaten binnen 60 dagen niet worden behaald, wordt het systeem kosteloos verder geoptimaliseerd).
"""
