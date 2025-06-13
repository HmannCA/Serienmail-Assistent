import os
from base64 import urlsafe_b64encode, urlsafe_b64decode
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# Funktion zum Generieren eines Fernet-Schlüssels aus dem ENCRYPTION_KEY
def _derive_key(password: str) -> bytes:
    # Ein fester Salt ist hier OK, da der "password" (ENCRYPTION_KEY) schon ein Geheimnis ist
    # und wir nur eine konsistente Schlüsselableitung benötigen.
    # In einer realen Anwendung für Benutzerpasswörter wäre ein zufälliger Salt pro Benutzer wichtig.
    salt = b'a_fixed_salt_for_simona_serienbrief' # Kann ein beliebiger fester Wert sein
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32, # Fernet requires a 32-byte key
        salt=salt,
        iterations=100000, # Empfohlene Anzahl von Iterationen
        backend=default_backend()
    )
    key = urlsafe_b64encode(kdf.derive(password.encode()))
    return key

_fernet_key = None # Wird einmalig geladen

def _get_fernet_instance(encryption_key_str: str):
    global _fernet_key
    if _fernet_key is None:
        # Key ableiten und Fernet-Instanz erstellen
        derived_key = _derive_key(encryption_key_str)
        _fernet_key = Fernet(derived_key)
    return _fernet_key

def encrypt_data(data: str, encryption_key_str: str) -> str:
    fernet = _get_fernet_instance(encryption_key_str)
    encrypted_bytes = fernet.encrypt(data.encode('utf-8'))
    return encrypted_bytes.decode('utf-8')

def decrypt_data(encrypted_data: str, encryption_key_str: str) -> str:
    fernet = _get_fernet_instance(encryption_key_str)
    decrypted_bytes = fernet.decrypt(encrypted_data.encode('utf-8'))
    return decrypted_bytes.decode('utf-8')

# Beispiel-Anwendung (nur zum Testen)
if __name__ == "__main__":
    # Simuliere das Laden des Schlüssels aus .env
    from dotenv import load_dotenv
    load_dotenv()
    TEST_ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

    if TEST_ENCRYPTION_KEY:
        print("Test der Verschlüsselungsfunktionen:")
        original_data = "Dies ist ein geheimer Text."
        encrypted = encrypt_data(original_data, TEST_ENCRYPTION_KEY)
        print(f"Original: {original_data}")
        print(f"Verschlüsselt: {encrypted}")

        decrypted = decrypt_data(encrypted, TEST_ENCRYPTION_KEY)
        print(f"Entschlüsselt: {decrypted}")

        assert original_data == decrypted
        print("Test erfolgreich!")
    else:
        print("ENCRYPTION_KEY nicht in .env gefunden. Bitte .env-Datei prüfen.")