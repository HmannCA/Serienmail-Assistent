import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import traceback
import secrets
import re

from fastapi import APIRouter, Request, Form, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates 

from sqlalchemy.orm import Session
from passlib.context import CryptContext

# Importiere lokale Module
from database import SessionLocal, User, PasswordResetToken, EmailVerificationToken, SmtpSettings 
from security import encrypt_data, decrypt_data 
from utils.email_utils import send_verification_email, send_password_reset_email, send_2fa_email

# NEU: Importiere die interne Testfunktion für SMTP aus utils
from utils.smtp_test_utils import test_smtp_connection_internal # Importiert die interne Testfunktion

# NEU: Import für get_smtp_settings
from settings_manager import get_smtp_settings


router = APIRouter()

# Datenbank-Abhängigkeit
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Abhängigkeit für Authentifizierung in Routen
def get_current_user_id(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        request.session["errorMessage"] = "Sie müssen angemeldet sein, um diese Seite aufzurufen."
        raise RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return user_id

# Provider-Funktionen für Templates und Pwd_Context
_templates_instance: Optional[Jinja2Templates] = None
_pwd_context_instance: Optional[CryptContext] = None

def set_global_templates_instance(instance: Jinja2Templates):
    global _templates_instance
    _templates_instance = instance

def get_templates_instance() -> Jinja2Templates:
    if _templates_instance is None:
        raise RuntimeError("Templates instance not initialized. Call set_global_templates_instance in main.py startup.")
    return _templates_instance

def set_global_pwd_context_instance(instance: CryptContext):
    global _pwd_context_instance
    _pwd_context_instance = instance

def get_pwd_context_instance() -> CryptContext:
    if _pwd_context_instance is None:
        raise RuntimeError("Pwd_context instance not initialized. Call set_global_pwd_context_instance in main.py startup.")
    return _pwd_context_instance

# Hilfsfunktionen für Authentifizierung
def verify_password(plain_password: str, hashed_password: str, pwd_context: CryptContext = Depends(get_pwd_context_instance)):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str, pwd_context: CryptContext = Depends(get_pwd_context_instance)):
    return pwd_context.hash(password)

def is_password_strong(password: str) -> bool:
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"[0-9]", password):
        return False
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", password):
        return False
    return True


# --- AUTHENTIFIZIERUNGS-ROUTEN ---

@router.get("/login", response_class=HTMLResponse)
async def get_login_form(request: Request, successMessage: Optional[str] = None, templates: Jinja2Templates = Depends(get_templates_instance)):
    session_success = request.session.pop("successMessage", None)
    if session_success:
        successMessage = session_success
    
    session_error = request.session.pop("errorMessage", None)
    if session_error:
        return templates.TemplateResponse("login.html", {"request": request, "error": session_error})

    return templates.TemplateResponse("login.html", {"request": request, "error": None, "successMessage": successMessage})

@router.post("/login", response_class=RedirectResponse)
async def post_login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db), pwd_context: CryptContext = Depends(get_pwd_context_instance)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not pwd_context.verify(password, user.password_hash):
        request.session["errorMessage"] = "Ungültige E-Mail-Adresse oder Passwort!"
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if not user.is_active:
        request.session["errorMessage"] = "Ihr Konto ist inaktiv. Bitte kontaktieren Sie den Administrator."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    if not user.is_verified:
        request.session["errorMessage"] = "Bitte bestätigen Sie zuerst Ihre E-Mail-Adresse über den Link in der Registrierungs-E-Mail."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    try:
        db.query(EmailVerificationToken).filter(
            (EmailVerificationToken.user_id == user.id) & 
            (EmailVerificationToken.expires_at < datetime.utcnow())
        ).delete()
        db.commit()

        two_fa_code = ''.join(secrets.choice('0123456789') for i in range(6)) 
        expires_at = datetime.utcnow() + timedelta(minutes=5)

        two_fa_token_entry = EmailVerificationToken(user_id=user.id, token=two_fa_code, expires_at=expires_at)
        db.add(two_fa_token_entry)
        db.commit()

        await send_2fa_email(user.email, two_fa_code, user.username)

        request.session["user_id_pending_2fa"] = user.id
        request.session["username_pending_2fa"] = user.username
        request.session["email_pending_2fa"] = user.email
        
        request.session["successMessage"] = "Ein 2FA-Code wurde an Ihre E-Mail-Adresse gesendet. Bitte geben Sie ihn ein."
        return RedirectResponse(url="/2fa-verify", status_code=status.HTTP_302_FOUND)

    except Exception as e:
        db.rollback()
        print(f"FEHLER bei der 2FA-Code-Generierung oder dem E-Mail-Versand: {e}")
        request.session["errorMessage"] = f"Ein unerwarteter Fehler ist beim Senden des 2FA-Codes aufgetreten. Bitte versuchen Sie es erneut oder kontaktieren Sie den Support. {e}"
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/2fa-verify", response_class=HTMLResponse)
async def get_2fa_verify_form(request: Request, templates: Jinja2Templates = Depends(get_templates_instance)):
    user_id_pending_2fa = request.session.get("user_id_pending_2fa")
    if not user_id_pending_2fa:
        request.session["errorMessage"] = "Ungültiger 2FA-Status. Bitte melden Sie sich erneut an."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    success_message = request.session.pop("successMessage", None)
    error_message = request.session.pop("errorMessage", None)
    
    return templates.TemplateResponse("2fa_verify.html", {"request": request, "error": error_message, "successMessage": success_message})

@router.post("/2fa-verify", response_class=RedirectResponse)
async def post_2fa_verify(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    user_id = request.session.get("user_id_pending_2fa")
    user_email = request.session.get("email_pending_2fa")
    
    if not user_id or not user_email:
        request.session["errorMessage"] = "Sitzung abgelaufen oder ungültig. Bitte melden Sie sich erneut an."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    user = db.query(User).filter(User.id == user_id, User.email == user_email).first()
    if not user:
        request.session["errorMessage"] = "Benutzer nicht gefunden. Bitte melden Sie sich erneut an."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    two_fa_token = db.query(EmailVerificationToken).filter(
        (EmailVerificationToken.user_id == user.id) & 
        (EmailVerificationToken.token == code)
    ).first()

    if not two_fa_token:
        request.session["errorMessage"] = "Ungültiger 2FA-Code. Bitte versuchen Sie es erneut."
        return RedirectResponse(url="/2fa-verify", status_code=status.HTTP_302_FOUND)
    
    if two_fa_token.expires_at < datetime.utcnow():
        db.delete(two_fa_token)
        db.commit()
        request.session["errorMessage"] = "Der 2FA-Code ist abgelaufen. Bitte melden Sie sich erneut an, um einen neuen Code zu erhalten."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # 2FA erfolgreich! Session finalisieren.
    db.delete(two_fa_token)
    db.commit()

    request.session["loggedin"] = True
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    
    del request.session["user_id_pending_2fa"]
    del request.session["username_pending_2fa"]
    del request.session["email_pending_2fa"]

    # NEU: Nach erfolgreichem 2FA-Login, SMTP-Status prüfen und in Session setzen (OHNE MAILVERSAND)
    smtp_settings = get_smtp_settings(db, user.id)
    if smtp_settings:
        # Führt einen stillen Test durch, sendet aber KEINE E-Mail (send_test_email=False)
        test_result = await test_smtp_connection_internal(
            smtp_settings['host'],
            smtp_settings['user'],
            smtp_settings['password'],
            smtp_settings['port'],
            smtp_settings['secure'],
            user.email, # Empfänger für Test-E-Mail (auch wenn nicht gesendet)
            send_test_email=False # WICHTIG: KEINE E-MAIL SENDEN BEI LOGIN
        )
        request.session["smtp_test_status"] = test_result["status"]
        request.session["smtp_test_message"] = test_result["message"]
    else:
        request.session["smtp_test_status"] = "not_set"
        request.session["smtp_test_message"] = "Ihre SMTP-Einstellungen sind noch nicht konfiguriert oder getestet."


    request.session["successMessage"] = "Login erfolgreich!"
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/register", response_class=HTMLResponse)
async def get_register_form(request: Request, templates: Jinja2Templates = Depends(get_templates_instance)):
    session_success = request.session.pop("successMessage", None)
    session_error = request.session.pop("errorMessage", None)
    return templates.TemplateResponse("register.html", {"request": request, "error": session_error, "successMessage": session_success})

@router.post("/register", response_class=RedirectResponse)
async def post_register(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...), confirm_password: str = Form(...), db: Session = Depends(get_db), pwd_context: CryptContext = Depends(get_pwd_context_instance)):
    if password != confirm_password:
        request.session["errorMessage"] = "Passwörter stimmen nicht überein!"
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)

    if not is_password_strong(password):
        request.session["errorMessage"] = "Das Passwort muss mindestens 8 Zeichen lang sein und Großbuchstaben, Kleinbuchstaben, Zahlen und Sonderzeichen enthalten."
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)

    if db.query(User).filter((User.email == email) | (User.username == username)).first():
        request.session["errorMessage"] = "E-Mail-Adresse oder Benutzername ist bereits vergeben!"
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)

    try:
        token = secrets.token_urlsafe(32)

        hashed_password = pwd_context.hash(password) 
        new_user = User(username=username, email=email, password_hash=hashed_password, is_active=True, is_verified=False)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        expires_at = datetime.utcnow() + timedelta(hours=24)
        verification_token_entry = EmailVerificationToken(user_id=new_user.id, token=token, expires_at=expires_at)
        db.add(verification_token_entry)
        db.commit()

        await send_verification_email(new_user.email, token, new_user.username)

        request.session["successMessage"] = "Registrierung erfolgreich! Bitte überprüfen Sie Ihre E-Mails, um Ihre Adresse zu verifizieren."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    except Exception as e:
        db.rollback()
        print(f"FEHLER bei der Registrierung: {e}")
        request.session["errorMessage"] = f"Fehler bei der Registrierung: {e}"
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)

@router.get("/verify-email/{token}", response_class=HTMLResponse)
async def verify_email(request: Request, token: str, db: Session = Depends(get_db), templates: Jinja2Templates = Depends(get_templates_instance)):
    verification_token = db.query(EmailVerificationToken).filter(EmailVerificationToken.token == token).first()

    if not verification_token:
        request.session["errorMessage"] = "Ungültiger oder abgelaufener Verifizierungslink."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    if verification_token.expires_at < datetime.utcnow():
        db.delete(verification_token) 
        db.commit()
        request.session["errorMessage"] = "Verifizierungslink ist abgelaufen. Bitte registrieren Sie sich erneut oder fordern Sie einen neuen Link an."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    user = db.query(User).filter(User.id == verification_token.user_id).first()
    if not user:
        request.session["errorMessage"] = "Benutzer nicht gefunden. Ungültiger Verifizierungslink."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    user.is_verified = True
    db.delete(verification_token) 
    db.commit()
    
    request.session["successMessage"] = "Ihre E-Mail-Adresse wurde erfolgreich verifiziert! Sie können sich jetzt anmelden."
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/forgot-password", response_class=HTMLResponse)
async def get_forgot_password_form(request: Request, templates: Jinja2Templates = Depends(get_templates_instance)):
    session_success = request.session.pop("successMessage", None)
    session_error = request.session.pop("errorMessage", None)
    return templates.TemplateResponse("forgot_password.html", {"request": request, "error": session_error, "successMessage": session_success})

@router.post("/forgot-password", response_class=RedirectResponse)
async def post_forgot_password(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        request.session["successMessage"] = "Wenn Ihre E-Mail-Adresse in unserem System registriert ist, erhalten Sie in Kürze eine E-Mail mit Anweisungen zum Zurücksetzen Ihres Passworts."
        return RedirectResponse(url="/forgot-password", status_code=status.HTTP_302_FOUND)

    try:
        db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).delete()
        db.commit()

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)
        reset_token_entry = PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at)
        db.add(reset_token_entry)
        db.commit()

        await send_password_reset_email(user.email, token, user.username)

        request.session["successMessage"] = "Wenn Ihre E-Mail-Adresse in unserem System registriert ist, erhalten Sie in Kürze eine E-Mail mit Anweisungen zum Zurücksetzen Ihres Passworts."
        return RedirectResponse(url="/forgot-password", status_code=status.HTTP_302_FOUND)

    except Exception as e:
        db.rollback()
        print(f"FEHLER beim Senden des Reset-Links: {e}")
        request.session["errorMessage"] = f"Fehler beim Senden des Reset-Links: {e}"
        return RedirectResponse(url="/forgot-password", status_code=status.HTTP_302_FOUND)

@router.get("/reset-password/{token}", response_class=HTMLResponse)
async def get_reset_password_form(request: Request, token: str, db: Session = Depends(get_db), templates: Jinja2Templates = Depends(get_templates_instance)):
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()

    if not reset_token:
        request.session["errorMessage"] = "Ungültiger oder abgelaufener Passwort-Reset-Link."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    if reset_token.expires_at < datetime.utcnow():
        db.delete(reset_token) 
        db.commit()
        request.session["errorMessage"] = "Passwort-Reset-Link ist abgelaufen. Bitte fordern Sie einen neuen Link an."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token})

@router.post("/reset-password/{token}", response_class=RedirectResponse)
async def post_reset_password(request: Request, token: str, password: str = Form(...), confirm_password: str = Form(...), db: Session = Depends(get_db), pwd_context: CryptContext = Depends(get_pwd_context_instance)):
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()

    if not reset_token or reset_token.expires_at < datetime.utcnow():
        request.session["errorMessage"] = "Ungültiger oder abgelaufener Passwort-Reset-Link."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if password != confirm_password:
        request.session["errorMessage"] = "Passwörter stimmen nicht überein!"
        return RedirectResponse(url=f"/reset-password/{token}", status_code=status.HTTP_302_FOUND)
    
    if not is_password_strong(password):
        request.session["errorMessage"] = "Das Passwort muss mindestens 8 Zeichen lang sein und Großbuchstaben, Kleinbuchstaben, Zahlen und Sonderzeichen enthalten."
        return RedirectResponse(url=f"/reset-password/{token}", status_code=status.HTTP_302_FOUND)

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        request.session["errorMessage"] = "Benutzer nicht gefunden. Ungültiger Reset-Link."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    user.password_hash = pwd_context.hash(password) 
    db.delete(reset_token) 
    db.commit()

    request.session["successMessage"] = "Ihr Passwort wurde erfolgreich zurückgesetzt! Sie können sich jetzt anmelden."
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    """Meldet den Benutzer ab und löscht die Session."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)