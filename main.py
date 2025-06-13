import os
from datetime import datetime, timedelta
import traceback
import shutil
import zipfile
import re 
import secrets # Beibehalten, da es global für Token-Generierung verwendet wird

# Imports für FastAPI und Starlette Kernkomponenten
from fastapi import FastAPI, Request, Form, Response, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy.orm import Session 
from passlib.context import CryptContext 
from dotenv import load_dotenv

# Importiere deine lokalen Module
from database import SessionLocal, engine, User, SmtpSettings, PasswordResetToken, EmailVerificationToken, create_db_and_tables

# NEU: Importiere die Router-Module
from routers import auth as auth_router_module
from routers import main_app as main_app_router_module
from routers import settings as settings_router_module

# Umgebungsvariablen laden
load_dotenv()

# --- FastAPI App Initialisierung ---
app = FastAPI(
    title="Serienbrief-Assistent",
    description="Ein Tool zum Erstellen und Versenden personalisierter Serienbriefe und E-Mails mit PDF-Anhängen."
)
app.debug = False # Debug-Modus DEAKTIVIERT


# Pfade für Uploads (GLOBAL VERFÜGBAR MACHEN UND HIER DEFINIEREN)
# Diese werden auch in pdf_generator.py und excel_processor.py verwendet
# DOCX_TEMP_DIR und PDF_GENERATED_DIR werden aus pdf_generator.py importiert, wo sie primär definiert sind.
from pdf_generator import DOCX_TEMP_DIR, PDF_GENERATED_DIR # Importiere die Pfade von dort
UPLOAD_DIR = "user_uploads" # Dieser Pfad ist spezifisch für die main/excel_processor


# --- Konfiguration ---
# Sessions
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "super-geheimes-session-key-bitte-aendern")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY) 

# Passwörter hash'en (GLOBAL VERFÜGBAR MACHEN)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Templating Engine (GLOBAL VERFÜGBAR MACHEN)
templates = Jinja2Templates(directory="templates")

# --- NEU: Globale Instanzen den Routern zuweisen ---
# Dies muss NACH der Initialisierung von templates und pwd_context geschehen.
auth_router_module.set_global_templates_instance(templates)
auth_router_module.set_global_pwd_context_instance(pwd_context)
main_app_router_module.set_global_templates_instance(templates)
settings_router_module.set_global_templates_instance(templates)


# --- Statische Dateien ---
# Verwende die global definierten Pfade hier
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount(f"/{PDF_GENERATED_DIR}", StaticFiles(directory=PDF_GENERATED_DIR), name=PDF_GENERATED_DIR)


# --- ROUTER REGISTRIEREN ---
# Alle Router-Module hier importieren und deren Router-Instanzen einbinden
app.include_router(auth_router_module.router)
app.include_router(main_app_router_module.router)
app.include_router(settings_router_module.router)


# --- Datenbank Abhängigkeit (bleibt hier, da es im Startup Event und globalen Depends verwendet wird) ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Startup Event (bleibt hier) ---
@app.on_event("startup")
async def startup_event():
    """
    Wird beim Start der Anwendung ausgeführt.
    Stellt sicher, dass die Datenbank und Tabellen existieren.
    Erstellt einen Standardbenutzer, falls keiner vorhanden ist.
    Stellt sicher, dass Upload- und PDF-Ordner existieren.
    """
    create_db_and_tables()
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == "test@example.com").first():
            # Verwende die globale pwd_context Instanz
            hashed_password = pwd_context.hash("testpass") # Direktnutzung der globalen pwd_context
            test_user = User(username="testuser", email="test@example.com", password_hash=hashed_password, is_verified=True, is_active=True)
            db.add(test_user)
            db.commit()
            db.refresh(test_user)

            ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
            if ENCRYPTION_KEY:
                # Importiere encrypt_data nur hier, wo es gebraucht wird
                from security import encrypt_data 
                encrypted_host = encrypt_data("smtp.example.com", ENCRYPTION_KEY)
                encrypted_user = encrypt_data("test@example.com", ENCRYPTION_KEY)
                encrypted_pass = encrypt_data("smtp_password", ENCRYPTION_KEY)
                encrypted_port = encrypt_data("587", ENCRYPTION_KEY)
                encrypted_secure = encrypt_data("tls", ENCRYPTION_KEY)

                test_smtp_settings = SmtpSettings(
                    user_id=test_user.id,
                    encrypted_host=encrypted_host,
                    encrypted_user=encrypted_user,
                    encrypted_pass=encrypted_pass,
                    encrypted_port=encrypted_port,
                    encrypted_secure=encrypted_secure
                )
                db.add(test_smtp_settings)
                db.commit()
            else:
                pass 
        else:
            pass 
    except Exception as e:
        db.rollback()
        print(f"Fehler bei der Initialisierung des Standardbenutzers oder der SMTP-Einstellungen: {e}") 
        pass 
    finally:
        db.close()
    
    # Sicherstellen, dass die Ordner existieren (verwende hier die globalen Pfade)
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)
    if not os.path.exists(os.path.join(UPLOAD_DIR, "word_templates")):
        os.makedirs(os.path.join(UPLOAD_DIR, "word_templates"))

    if not os.path.exists(PDF_GENERATED_DIR): 
        os.makedirs(PDF_GENERATED_DIR)
    if not os.path.exists(DOCX_TEMP_DIR): 
        os.makedirs(DOCX_TEMP_DIR)


# --- Globale Fehlerbehandlung (bleibt hier) ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        request.session["errorMessage"] = exc.detail 
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    return HTMLResponse(
        content=f"<h1>HTTP-Fehler {exc.status_code}</h1><p>{exc.detail}</p>",
        status_code=exc.status_code
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    error_traceback = traceback.format_exc()
    return HTMLResponse(
        content=f"<h1>Interner Serverfehler</h1><p>Ein unerwarteter Fehler ist aufgetreten.</p><pre>{error_traceback}</pre>",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )