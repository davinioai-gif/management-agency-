import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMIRHAN_EMAIL

logger = logging.getLogger(__name__)

class NotificationHandler:
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
