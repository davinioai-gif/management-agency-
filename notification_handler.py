import smtplib
import logging
import urllib.request
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMIRHAN_EMAIL, N8N_HANDOVER_WEBHOOK_URL

logger = logging.getLogger(__name__)

class NotificationHandler:
    @staticmethod
    def send_n8n_handover_webhook(name: str, phone: str, message: str) -> bool:
        """
        Sends handover details (name, phone, message) to the configured n8n webhook URL.
        """
        logger.info(f"[NOTIFICATION] Triggered n8n handover webhook to {N8N_HANDOVER_WEBHOOK_URL}")
        
        if not N8N_HANDOVER_WEBHOOK_URL:
            logger.warning("[NOTIFICATION] N8N_HANDOVER_WEBHOOK_URL is not set.")
            return False
            
        payload = {
            "name": name,
            "phone": phone,
            "message": message,
            "msg": message
        }
        
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                N8N_HANDOVER_WEBHOOK_URL,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req) as response:
                if response.status in (200, 201):
                    logger.info("Handover webhook sent successfully to n8n.")
                    return True
                else:
                    logger.warning(f"n8n webhook returned status: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Failed to trigger n8n handover webhook: {e}")
            return False

    @staticmethod
    def send_email_notification(subject: str, body: str, recipient: str = EMIRHAN_EMAIL) -> bool:
        """
        Sends an email notification. Falls back to logging if SMTP settings are missing.
        """
        logger.info(f"[NOTIFICATION] Triggered email notification to {recipient} with subject: {subject}")
        
        # Check if SMTP details are configured
        if not all([SMTP_USERNAME, SMTP_PASSWORD]):
            logger.warning("[NOTIFICATION] SMTP credentials not set. Logging email content to terminal/logs instead:")
            logger.warning(f"--- EMAIL TO: {recipient} ---\nSubject: {subject}\nBody:\n{body}\n----------------------")
            return True
            
        try:
            msg = MIMEMultipart()
            msg['From'] = SMTP_USERNAME
            msg['To'] = recipient
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, recipient, msg.as_string())
            server.quit()
            
            logger.info(f"Email sent successfully to {recipient}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False
