import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import re
import secrets
from datetime import datetime, timedelta # Diese Imports könnten hier benötigt werden, wenn Sie sie für Token-Gültigkeit direkt nutzen, aber im Moment sind sie in main.py für Token-Erstellung
from dotenv import load_dotenv

# Lade Umgebungsvariablen (wichtig, da dieses Modul sie direkt nutzen wird)
load_dotenv()


async def send_verification_email(user_email: str, token: str, username: str = "Nutzer"):
    app_base_url = os.getenv('APP_BASE_URL', 'http://127.0.0.1:8000') 
    verification_link = f"{app_base_url}/verify-email/{token}"
    subject = "E-Mail-Verifizierung für Serienmail-Assistent"
    body_html = f"""
    <html>
        <body>
            <p>Hallo {username},</p>
            <p>Vielen Dank für Ihre Registrierung beim Serienmail-Assistenten. Bitte klicken Sie auf den folgenden Link, um Ihre E-Mail-Adresse zu verifizieren:</p>
            <p><a href="{verification_link}">{verification_link}</a></p>
            <p>Dieser Link ist 24 Stunden gültig.</p>
            <p>Wenn Sie dies nicht angefordert haben, können Sie diese E-Mail ignorieren.</p>
            <p>Ihr Serienmail-Assistent Team</p>
        </body>
    </html>
    """
    
    app_smtp_user = os.getenv('APP_SMTP_USER')
    app_smtp_pass = os.getenv('APP_SMTP_PASS')
    app_smtp_host = os.getenv('APP_SMTP_HOST', 'smtp.example.com')
    app_smtp_port = os.getenv('APP_SMTP_PORT', '587')
    app_smtp_secure = os.getenv('APP_SMTP_SECURE', 'tls')

    if not app_smtp_user or not app_smtp_pass:
        print("WARNUNG: APP_SMTP_USER oder APP_SMTP_PASS nicht in .env gefunden. Verifizierungs-E-Mail kann nicht gesendet werden.")
        return 
    
    try:
        if app_smtp_secure == 'tls':
            server = smtplib.SMTP(app_smtp_host, int(app_smtp_port), timeout=30)
            server.starttls()
        elif app_smtp_secure == 'ssl':
            server = smtplib.SMTP_SSL(app_smtp_host, int(app_smtp_port), timeout=30)
        else:
            server = smtplib.SMTP(app_smtp_host, int(app_smtp_port), timeout=30)
        
        server.login(app_smtp_user, app_smtp_pass)

        msg = MIMEMultipart('alternative')
        msg['From'] = f"Serienmail-Assistent <{app_smtp_user}>"
        msg['To'] = user_email
        msg['Subject'] = subject

        plain_text_body = re.sub(r'<[^>]+>', '', body_html).strip()
        
        part1 = MIMEText(plain_text_body, 'plain')
        part2 = MIMEText(body_html, 'html')
        msg.attach(part1)
        msg.attach(part2)

        server.send_message(msg)
        server.quit()
        print(f"Verifizierungs-E-Mail erfolgreich an {user_email} gesendet.")
    except Exception as e:
        print(f"FEHLER beim Senden der Verifizierungs-E-Mail an {user_email}: {e}")

async def send_password_reset_email(user_email: str, token: str, username: str = "Nutzer"):
    app_base_url = os.getenv('APP_BASE_URL', 'http://127.0.0.1:8000')
    reset_link = f"{app_base_url}/reset-password/{token}"
    subject = "Passwort zurücksetzen für Serienmail-Assistent"
    body_html = f"""
    <html>
        <body>
            <p>Hallo {username},</p>
            <p>Sie haben das Zurücksetzen Ihres Passworts für Ihr Konto beim Serienmail-Assistenten angefordert.</p>
            <p>Bitte klicken Sie auf den folgenden Link, um ein neues Passwort festzulegen:</p>
            <p><a href="{reset_link}">{reset_link}</a></p>
            <p>Dieser Link ist 1 Stunde gültig.</p>
            <p>Wenn Sie dies nicht angefordert haben, können Sie diese E-Mail ignorieren.</p>
            <p>Ihr Serienmail-Assistent Team</p>
        </body>
    </html>
    """
    app_smtp_user = os.getenv('APP_SMTP_USER')
    app_smtp_pass = os.getenv('APP_SMTP_PASS')
    app_smtp_host = os.getenv('APP_SMTP_HOST', 'smtp.example.com')
    app_smtp_port = os.getenv('APP_SMTP_PORT', '587')
    app_smtp_secure = os.getenv('APP_SMTP_SECURE', 'tls')

    if not app_smtp_user or not app_smtp_pass:
        print("WARNUNG: APP_SMTP_USER oder APP_SMTP_PASS nicht in .env gefunden. Passwort-Reset-E-Mail kann nicht gesendet werden.")
        return 
    
    try:
        if app_smtp_secure == 'tls':
            server = smtplib.SMTP(app_smtp_host, int(app_smtp_port), timeout=30)
            server.starttls()
        elif app_smtp_secure == 'ssl':
            server = smtplib.SMTP_SSL(app_smtp_host, int(app_smtp_port), timeout=30)
        else:
            server = smtplib.SMTP(app_smtp_host, int(app_smtp_port), timeout=30)
        
        server.login(app_smtp_user, app_smtp_pass)

        msg = MIMEMultipart('alternative')
        msg['From'] = f"Serienmail-Assistent <{app_smtp_user}>"
        msg['To'] = user_email
        msg['Subject'] = subject

        plain_text_body = re.sub(r'<[^>]+>', '', body_html).strip()
        
        part1 = MIMEText(plain_text_body, 'plain')
        part2 = MIMEText(body_html, 'html')
        msg.attach(part1)
        msg.attach(part2)

        server.send_message(msg)
        server.quit()
        print(f"Passwort-Reset-E-Mail erfolgreich an {user_email} gesendet.")
    except Exception as e:
        print(f"FEHLER beim Senden der Passwort-Reset-E-Mail an {user_email}: {e}")

async def send_2fa_email(user_email: str, two_fa_code: str, username: str = "Nutzer"):
    subject = "Ihr 2FA-Anmeldecode für Serienmail-Assistent"
    body_html = f"""
    <html>
        <body>
            <p>Hallo {username},</p>
            <p>Ihr Anmeldecode für die Zwei-Faktor-Authentifizierung (2FA) lautet:</p>
            <h3 style="color: #0d6efd; font-size: 24px;">{two_fa_code}</h3>
            <p>Dieser Code ist 5 Minuten gültig.</p>
            <p>Bitte geben Sie diesen Code auf der Anmeldeseite ein.</p>
            <p>Wenn Sie diesen Login nicht angefordert haben, können Sie diese E-Mail ignorieren. Bitte kontaktieren Sie uns, wenn Sie Sicherheitsbedenken haben.</p>
            <p>Ihr Serienmail-Assistent Team</p>
        </body>
    </html>
    """
    
    app_smtp_user = os.getenv('APP_SMTP_USER')
    app_smtp_pass = os.getenv('APP_SMTP_PASS')
    app_smtp_host = os.getenv('APP_SMTP_HOST', 'smtp.example.com')
    app_smtp_port = os.getenv('APP_SMTP_PORT', '587')
    app_smtp_secure = os.getenv('APP_SMTP_SECURE', 'tls')

    if not app_smtp_user or not app_smtp_pass:
        print("WARNUNG: APP_SMTP_USER oder APP_SMTP_PASS nicht in .env gefunden. 2FA-E-Mail kann nicht gesendet werden.")
        return 
    
    try:
        if app_smtp_secure == 'tls':
            server = smtplib.SMTP(app_smtp_host, int(app_smtp_port), timeout=30)
            server.starttls()
        elif app_smtp_secure == 'ssl':
            server = smtplib.SMTP_SSL(app_smtp_host, int(app_smtp_port), timeout=30)
        else:
            server = smtplib.SMTP(app_smtp_host, int(app_smtp_port), timeout=30)
        
        server.login(app_smtp_user, app_smtp_pass)

        msg = MIMEMultipart('alternative')
        msg['From'] = f"Serienmail-Assistent <{app_smtp_user}>"
        msg['To'] = user_email
        msg['Subject'] = subject

        plain_text_body = re.sub(r'<[^>]+>', '', body_html).strip()
        
        part1 = MIMEText(plain_text_body, 'plain')
        part2 = MIMEText(body_html, 'html')
        msg.attach(part1)
        msg.attach(part2)

        server.send_message(msg)
        server.quit()
        print(f"2FA-E-Mail erfolgreich an {user_email} gesendet.")
    except Exception as e:
        print(f"FEHLER beim Senden der 2FA-E-Mail an {user_email}: {e}")