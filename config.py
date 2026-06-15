import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Config

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "O4gWVTFQnwUqL7xg")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "conversation")

# OpenAI Config
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "gpt-4o")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "gpt-4o-mini")

# Unipile Config
UNIPILE_API_KEY = os.getenv("UNIPILE_API_KEY")
UNIPILE_API_URL = os.getenv("UNIPILE_API_URL", "https://api.unipile.com/v1")
UNIPILE_CHAT_ID = os.getenv("UNIPILE_CHAT_ID")  # Default sending chat/channel ID if needed

# Calendly Config — Only these links exist on Calendly:
# - Intake call (for podcast, events, influencer, and photostudio with extras/photographer)
# - 3 photostudio direct links based on duration (only if no photographer and no extras)
CALENDLY_INTAKE_URL = os.getenv("CALENDLY_INTAKE_URL", "https://calendly.com/bhmanagement/intake-call-beerthuizen-management")
CALENDLY_PHOTO_2H_URL = "https://calendly.com/bhmanagement/fotostudio-huren-120"
CALENDLY_PHOTO_4H_URL = "https://calendly.com/bhmanagement/fotostudio-huren-240"
CALENDLY_PHOTO_8H_URL = "https://calendly.com/bhmanagement/fotostudio-huren-480"

# Notifications Config
EMIRHAN_EMAIL = os.getenv("EMIRHAN_EMAIL", "emirhan@beerthuizenmanagement.nl")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
N8N_HANDOVER_WEBHOOK_URL = os.getenv("N8N_HANDOVER_WEBHOOK_URL", "https://davinioai.app.n8n.cloud/webhook/mailSendingtoclientforwebandapp")

