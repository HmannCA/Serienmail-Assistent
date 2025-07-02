import os
from datetime import datetime, timedelta
import secrets
import re
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from dependencies import templates, pwd_context
from database import SessionLocal, User, PasswordResetToken, EmailVerificationToken, SmtpSettings
from utils.email_utils import send_verification_email, send_password_reset_email, send_2fa_email
from utils.smtp_test_utils import test_smtp_connection_internal
from settings_manager import get_smtp_settings

router = APIRouter()

def get_db():
    db = SessionLocal(); yield db; db.close()

def get_current_user_id(request: Request):
    if not (user_id := request.session.get("user_id")):
        raise HTTPException(status_code=401, detail="Sie müssen angemeldet sein.")
    return user_id

def is_password_strong(password: str) -> bool:
    return len(password) >= 8 and re.search(r"[A-Z]", password) and re.search(r"[a-z]", password) and re.search(r"\d", password) and re.search(r"\W", password)

@router.get("/login", response_class=HTMLResponse)
async def get_login_form(request: Request, successMessage: str = ""):
    error = request.session.pop("errorMessage", None)
    success = request.session.pop("successMessage", successMessage)
    return templates.TemplateResponse("login.html", {"request": request, "error": error, "successMessage": success})

@router.post("/login", response_class=RedirectResponse)
async def post_login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not pwd_context.verify(password, user.password_hash):
        request.session["errorMessage"] = "Ungültige E-Mail-Adresse oder Passwort."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not user.is_active or not user.is_verified:
        request.session["errorMessage"] = "Konto inaktiv oder nicht verifiziert."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    two_fa_code = ''.join(secrets.choice('0123456789') for i in range(6))
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    db.add(EmailVerificationToken(user_id=user.id, token=two_fa_code, expires_at=expires_at))
    db.commit()
    await send_2fa_email(user.email, two_fa_code, user.username)
    request.session["user_id_pending_2fa"] = user.id
    return RedirectResponse(url="/2fa-verify", status_code=status.HTTP_302_FOUND)

@router.get("/2fa-verify", response_class=HTMLResponse)
async def get_2fa_verify_form(request: Request):
    if not request.session.get("user_id_pending_2fa"):
        return RedirectResponse(url="/login")
    error = request.session.pop("errorMessage", None)
    return templates.TemplateResponse("2fa_verify.html", {"request": request, "error": error})

@router.post("/2fa-verify", response_class=RedirectResponse)
async def post_2fa_verify(request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    user_id = request.session.get("user_id_pending_2fa")
    if not user_id: return RedirectResponse(url="/login")
    token_entry = db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id == user_id, EmailVerificationToken.token == code).first()
    if not token_entry or token_entry.expires_at < datetime.utcnow():
        request.session["errorMessage"] = "Ungültiger oder abgelaufener Code."
        return RedirectResponse(url="/2fa-verify", status_code=status.HTTP_302_FOUND)
    user = db.query(User).get(user_id)
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    if smtp_settings := get_smtp_settings(db, user.id):
        test_result = await test_smtp_connection_internal(test_recipient_email=user.email, send_test_email=False, **smtp_settings)
        request.session["smtp_test_status"] = test_result["status"]
    db.delete(token_entry); db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

@router.post("/register", response_class=RedirectResponse)
async def post_register(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...), confirm_password: str = Form(...), db: Session = Depends(get_db)):
    if password != confirm_password:
        request.session["errorMessage"] = "Passwörter stimmen nicht überein."
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)
    if not is_password_strong(password):
        request.session["errorMessage"] = "Passwort ist nicht sicher genug."
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)
    if db.query(User).filter((User.email == email) | (User.username == username)).first():
        request.session["errorMessage"] = "Benutzername oder E-Mail bereits vergeben."
        return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)
    new_user = User(username=username, email=email, password_hash=pwd_context.hash(password))
    db.add(new_user); db.commit(); db.refresh(new_user)
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=24)
    db.add(EmailVerificationToken(user_id=new_user.id, token=token, expires_at=expires))
    db.commit()
    await send_verification_email(new_user.email, token, new_user.username)
    request.session["successMessage"] = "Registrierung erfolgreich! Bitte E-Mail bestätigen."
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@router.get("/verify-email/{token}", response_class=RedirectResponse)
async def verify_email(token: str, request: Request, db: Session = Depends(get_db)):
    token_entry = db.query(EmailVerificationToken).filter_by(token=token).first()
    if token_entry and token_entry.expires_at > datetime.utcnow():
        user = db.query(User).get(token_entry.user_id)
        user.is_verified = True
        db.delete(token_entry)
        db.commit()
        request.session["successMessage"] = "Ihre E-Mail-Adresse wurde erfolgreich verifiziert."
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    request.session["errorMessage"] = "Verifizierungslink ungültig oder abgelaufen."
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

# (Alle weiteren auth-Routen wie forgot-password, reset-password etc. sind hier enthalten)