
import smtplib
import secrets
import time
from email.mime.text import MIMEText

# Email server settings
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
#EMAIL_USERNAME = enter your email 
#EMAIL_PASSWORD = enter your app password 

# Dictionary to store active PINs: {email: (pin, timestamp)}
active_pins = {}

def generate_pin():
    """Generate a secure 6-digit PIN."""
    return str(secrets.randbelow(900000) + 100000)  # Ensures 6-digit

def send_pin_email(to_email):
    """Generate and send a PIN to the user's email."""
    pin = generate_pin()
    active_pins[to_email] = (pin, time.time())  # Store with timestamp

    msg = MIMEText(f"Your login PIN is: {pin}. It expires in 10 minutes.")
    msg["Subject"] = "Your Secure Login PIN"
    msg["From"] = EMAIL_USERNAME
    msg["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USERNAME, to_email, msg.as_string())
        print(f"PIN sent to {to_email}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def verify_pin(email, entered_pin):
    """Check if the entered PIN is valid and not expired (10 minutes)."""
    if email not in active_pins:
        return False

    pin, timestamp = active_pins[email]
    current_time = time.time()

    if current_time - timestamp > 600:  # 10 minutes
        del active_pins[email]
        return False

    if pin == entered_pin:
        del active_pins[email]
        return True

    return False


