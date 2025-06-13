import os
import smtplib
from email.mime.text import MIMEText
from typing import Dict, Any 
from dotenv import load_dotenv

load_dotenv()

ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

if not ENCRYPTION_KEY:
    print("WARNUNG (utils/smtp_test_utils.py): ENCRYPTION_KEY nicht in .env gefunden. SMTP-Funktionen könnten eingeschränkt sein.")


async def test_smtp_connection_internal(host: str, user: str, password: str, port: str, secure: str, test_recipient_email: str, send_test_email: bool = True) -> Dict[str, str]:
    """
    Testet die SMTP-Verbindung und sendet optional eine Test-E-Mail.
    send_test_email: Wenn True, wird eine Test-E-Mail gesendet. Wenn False, wird nur die Verbindung geprüft.
    """
    try:
        port_int = int(port)

        if secure == 'tls':
            server = smtplib.SMTP(host, port_int, timeout=10) 
            server.starttls()
        elif secure == 'ssl':
            server = smtplib.SMTP_SSL(host, port_int, timeout=10) 
        else: 
            server = smtplib.SMTP(host, port_int, timeout=10) 
        
        server.login(user, password)

        if send_test_email: # NEU: Bedingung für den E-Mail-Versand
            msg = MIMEText('Dies ist eine Test-E-Mail von Ihrem Serienmail-Assistenten. Ihre SMTP-Einstellungen funktionieren!')
            msg['Subject'] = 'SMTP-Test: Serienmail-Assistent'
            msg['From'] = user
            msg['To'] = test_recipient_email
            
            server.sendmail(user, test_recipient_email, msg.as_string())
            print(f"DEBUG (smtp_test_utils.py): Test-E-Mail an {test_recipient_email} gesendet.") 

        server.quit()
        
        return {"status": "success", "message": f"SMTP-Einstellungen erfolgreich getestet!" + (" Eine Test-E-Mail wurde an " + test_recipient_email + " gesendet." if send_test_email else "")}
    except smtplib.SMTPAuthenticationError:
        return {"status": "error", "message": "SMTP-Fehler: Authentifizierung fehlgeschlagen. Überprüfen Sie Benutzername und Passwort."}
    except smtplib.SMTPConnectError as e:
        return {"status": "error", "message": f"SMTP-Fehler: Verbindung fehlgeschlagen. Überprüfen Sie Host und Port. Details: {e}"}
    except smtplib.SMTPException as e:
        return {"status": "error", "message": f"Ein SMTP-Fehler ist aufgetreten: {e}. Überprüfen Sie Ihre Einstellungen (Host, Port, Secure-Typ, Anmeldedaten)."}
    except ValueError as e:
        return {"status": "error", "message": f"Konfigurationsfehler: Der Port muss eine gültige Zahl sein. Details: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Ein unerwarteter Fehler ist aufgetreten: {e}. Überprüfen Sie Ihre Host, Port, Benutzer und Passwort-Einstellungen."}