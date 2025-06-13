import os
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from database import SmtpSettings
from security import encrypt_data, decrypt_data
from dotenv import load_dotenv

# Lade Umgebungsvariablen aus .env-Datei
load_dotenv()

ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

if not ENCRYPTION_KEY:
    print("WARNUNG (settings_manager.py): ENCRYPTION_KEY nicht in .env gefunden. SMTP-Einstellungen können nicht verarbeitet werden.")
else:
    print("DEBUG (settings_manager.py): ENCRYPTION_KEY erfolgreich geladen.") # NEU: Bestätigung, dass der Schlüssel geladen wurde


def save_smtp_settings(
    db: Session,
    user_id: int,
    host: str,
    user: str,
    password: str,
    port: str,
    secure: str
) -> None:
    # Debug-Ausgabe beim Speichern
    print(f"DEBUG (settings_manager.py): save_smtp_settings aufgerufen für user_id={user_id}. Host={host}, User={user}") # NEU
    if not ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY nicht verfügbar. Kann SMTP-Einstellungen nicht speichern.")

    encrypted_host = encrypt_data(host, ENCRYPTION_KEY)
    encrypted_user = encrypt_data(user, ENCRYPTION_KEY)
    encrypted_pass = encrypt_data(password, ENCRYPTION_KEY)
    encrypted_port = encrypt_data(port, ENCRYPTION_KEY)
    encrypted_secure = encrypt_data(secure, ENCRYPTION_KEY)

    settings = db.query(SmtpSettings).filter(SmtpSettings.user_id == user_id).first()
    if settings:
        print(f"DEBUG (settings_manager.py): Bestehende SMTP-Einstellungen für user_id={user_id} aktualisiert.") # NEU
        settings.encrypted_host = encrypted_host
        settings.encrypted_user = encrypted_user
        settings.encrypted_pass = encrypted_pass
        settings.encrypted_port = encrypted_port
        settings.encrypted_secure = encrypted_secure
    else:
        print(f"DEBUG (settings_manager.py): Neue SMTP-Einstellungen für user_id={user_id} erstellt.") # NEU
        settings = SmtpSettings(
            user_id=user_id,
            encrypted_host=encrypted_host,
            encrypted_user=encrypted_user,
            encrypted_pass=encrypted_pass,
            encrypted_port=encrypted_port,
            encrypted_secure=encrypted_secure
        )
        db.add(settings)
    db.commit()
    print(f"DEBUG (settings_manager.py): SMTP-Einstellungen für user_id={user_id} in DB committet.") # NEU

def get_smtp_settings(db: Session, user_id: int) -> Optional[Dict[str, str]]:
    print(f"DEBUG (settings_manager.py): get_smtp_settings aufgerufen für user_id={user_id}.") # NEU
    if not ENCRYPTION_KEY:
        print("FEHLER (settings_manager.py): ENCRYPTION_KEY nicht verfügbar. Kann SMTP-Einstellungen nicht entschlüsseln.") # NEU
        return None

    settings = db.query(SmtpSettings).filter(SmtpSettings.user_id == user_id).first()
    if settings:
        print(f"DEBUG (settings_manager.py): SMTP-Einstellungen für user_id={user_id} in DB gefunden. Versuche zu entschlüsseln.") # NEU
        try:
            # Hier können wir print-Statements hinzufügen, um die verschlüsselten Werte zu sehen
            # print(f"DEBUG: Verschlüsselt: host={settings.encrypted_host[:10]}..., user={settings.encrypted_user[:10]}...") # Nur die ersten paar Zeichen

            decrypted_host = decrypt_data(settings.encrypted_host, ENCRYPTION_KEY)
            decrypted_user = decrypt_data(settings.encrypted_user, ENCRYPTION_KEY)
            decrypted_pass = decrypt_data(settings.encrypted_pass, ENCRYPTION_KEY)
            decrypted_port = decrypt_data(settings.encrypted_port, ENCRYPTION_KEY)
            decrypted_secure = decrypt_data(settings.encrypted_secure, ENCRYPTION_KEY)

            print(f"DEBUG (settings_manager.py): SMTP-Daten erfolgreich entschlüsselt für user_id={user_id}. Host={decrypted_host}, User={decrypted_user}") # NEU
            return {
                "host": decrypted_host,
                "user": decrypted_user,
                "password": decrypted_pass,
                "port": decrypted_port,
                "secure": decrypted_secure
            }
        except Exception as e:
            print(f"FEHLER (settings_manager.py): Entschlüsselung der SMTP-Einstellungen fehlgeschlagen für user_id={user_id}: {e}") # NEU
            # Wenn Entschlüsselung fehlschlägt, ist der ENCRYPTION_KEY möglicherweise anders als der beim Speichern
            # Oder die Daten sind korrupt
            return None
    print(f"DEBUG (settings_manager.py): Keine SMTP-Einstellungen für user_id={user_id} in DB gefunden.") # NEU
    return None