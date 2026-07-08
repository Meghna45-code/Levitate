import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
import logging

from backend.app.config import settings

logger = logging.getLogger(__name__)

def send_otp_email_task(recipient: str, otp: str, is_reset: bool = False):
    """
    Sends an email containing the 6-digit OTP code to the recipient.
    This function runs in a FastAPI background task to ensure it doesn't block requests.
    """
    # If not configured, just log it and exit
    if not settings.SMTP_HOST or not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning(
            "SMTP is not configured properly (missing host, username, or password). "
            f"Would have sent OTP {otp} to {recipient}."
        )
        print(f"SMTP is not configured. OTP: {otp} for {recipient}", file=sys.stderr)
        return

    subject = "Reset Your Password - Levitate" if is_reset else "Verify Your Email - Levitate"
    sender = settings.SMTP_SENDER or settings.SMTP_USERNAME

    # HTML Body
    action_text = "reset your password" if is_reset else "verify your new account"
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #f8fafc;
                margin: 0;
                padding: 0;
                color: #1e293b;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background: #ffffff;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
                border: 1px solid #e2e8f0;
            }}
            .header {{
                background: linear-gradient(135deg, #d3968c 0%, #839958 50%, #105666 100%);
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{
                color: #ffffff;
                margin: 0;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }}
            .content {{
                padding: 40px 30px;
                line-height: 1.6;
            }}
            .content p {{
                margin: 0 0 20px 0;
                font-size: 16px;
            }}
            .otp-container {{
                background-color: #f1f5f9;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 20px;
                text-align: center;
                margin: 30px 0;
            }}
            .otp-code {{
                font-size: 32px;
                font-weight: 700;
                letter-spacing: 4px;
                color: #105666;
                margin: 0;
            }}
            .footer {{
                background-color: #f8fafc;
                padding: 20px;
                text-align: center;
                font-size: 12px;
                color: #64748b;
                border-top: 1px solid #e2e8f0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Levitate Assistant</h1>
            </div>
            <div class="content">
                <p>Hello,</p>
                <p>Thank you for using Levitate. Use the following 6-digit PIN to {action_text}. This code will expire in 10 minutes.</p>
                <div class="otp-container">
                    <div class="otp-code">{otp}</div>
                </div>
                <p>If you did not initiate this request, please ignore this email or contact support.</p>
                <p>Best regards,<br>The Levitate Team</p>
            </div>
            <div class="footer">
                &copy; Levitate Voice Scheduling Assistant. All rights reserved.
            </div>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    # Attach both plain text and HTML versions
    text_content = f"Hello,\n\nUse the following 6-digit PIN to {action_text}: {otp}\n\nThis code will expire in 10 minutes.\n\nBest regards,\nThe Levitate Team"
    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        # Connect to server
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        logger.info(f"Verification email successfully sent to {recipient}")
        print(f"Verification email successfully sent to {recipient}", file=sys.stderr)
    except Exception as e:
        logger.error(f"Failed to send email to {recipient} via SMTP: {e}", exc_info=True)
        print(f"Failed to send email to {recipient} via SMTP: {e}", file=sys.stderr)
