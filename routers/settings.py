from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse 
from fastapi.templating import Jinja2Templates # HINZUGEFÜGT: Import von Jinja2Templates

import smtplib 
from email.mime.text import MIMEText 

from sqlalchemy.orm import Session 

# Importiere lokale Module
from database import SessionLocal 
from settings_manager import save_smtp_settings, get_smtp_settings

# Importiere Abhängigkeiten und gemeinsame Objekte aus anderen Modulen
from routers.auth import get_current_user_id 
from utils.smtp_test_utils import test_smtp_connection_internal 


router = APIRouter()

# Datenbank-Abhängigkeit
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Abhängigkeit für templates
_templates_instance: Optional[Jinja2Templates] = None

def set_global_templates_instance(instance: Jinja2Templates):
    global _templates_instance
    _templates_instance = instance

def get_templates_instance() -> Jinja2Templates:
    if _templates_instance is None:
        raise RuntimeError("Templates instance not initialized. Call set_global_templates_instance in main.py startup.")
    return _templates_instance


@router.get("/settings", response_class=HTMLResponse)
async def get_settings_form(request: Request, db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id), templates: Jinja2Templates = Depends(get_templates_instance)):
    """Zeigt das SMTP-Einstellungen-Formular an und lädt vorhandene Einstellungen."""
    settings = get_smtp_settings(db, current_user_id)

    smtp_host = settings.get("host") if settings else ''
    smtp_user = settings.get("user") if settings else ''
    smtp_pass = settings.get("password") if settings else ''
    smtp_port = settings.get("port") if settings else '587'
    smtp_secure = settings.get("secure") if settings else 'tls'

    success_message = request.session.pop("successMessage", None)
    error_message = request.session.pop("errorMessage", None)
    
    smtp_test_status = request.session.pop("smtp_test_status", None)
    smtp_test_message = request.session.pop("smtp_test_message", None)

    context = {
        "request": request,
        "smtp_host": smtp_host,
        "smtp_user": smtp_user,
        "smtp_pass": smtp_pass,
        "smtp_port": smtp_port,
        "smtp_secure": smtp_secure,
        "successMessage": success_message,
        "errorMessage": error_message,
        "smtp_test_status": smtp_test_status, 
        "smtp_test_message": smtp_test_message 
    }
    return templates.TemplateResponse("settings.html", context)

@router.post("/settings", response_class=RedirectResponse)
async def post_settings(request: Request,
                        smtp_host: str = Form(...),
                        smtp_user: str = Form(...),
                        smtp_pass: str = Form(...),
                        smtp_port: str = Form(...),
                        smtp_secure: str = Form(...),
                        db: Session = Depends(get_db),
                        current_user_id: int = Depends(get_current_user_id)):
    """Speichert die SMTP-Einstellungen."""
    try:
        save_smtp_settings(db, current_user_id, smtp_host, smtp_user, smtp_pass, smtp_port, smtp_secure)
        
        test_result = await test_smtp_connection_internal(smtp_host, smtp_user, smtp_pass, smtp_port, smtp_secure, smtp_user) 
        
        request.session["smtp_test_status"] = test_result["status"]
        request.session["smtp_test_message"] = test_result["message"]

        if test_result["status"] == "success":
            request.session["successMessage"] = "Einstellungen erfolgreich gespeichert und SMTP-Verbindung getestet!"
            return RedirectResponse(url="/?smtp_test_ok=true", status_code=status.HTTP_302_FOUND) 
        else:
            request.session["errorMessage"] = f"Einstellungen gespeichert, aber SMTP-Test fehlgeschlagen: {test_result['message']}"
            return RedirectResponse(url="/settings", status_code=status.HTTP_302_FOUND)

    except Exception as e:
        request.session["errorMessage"] = f"Fehler beim Speichern der Einstellungen: {e}"
        return RedirectResponse(url="/settings", status_code=status.HTTP_302_FOUND)

# Endpunkt zum Testen der SMTP-Verbindung
@router.post("/settings/test-smtp", response_class=JSONResponse)
async def test_smtp_connection_endpoint(request: Request,
                                        smtp_host: str = Form(...),
                                        smtp_user: str = Form(...),
                                        smtp_pass: str = Form(...),
                                        smtp_port: str = Form(...),
                                        smtp_secure: str = Form(...),
                                        current_user_id: int = Depends(get_current_user_id)):
    
    test_email_recipient = smtp_user
    
    result = await test_smtp_connection_internal(smtp_host, smtp_user, smtp_pass, smtp_port, smtp_secure, test_email_recipient)
    
    request.session["smtp_test_status"] = result["status"]
    request.session["smtp_test_message"] = result["message"]

    if result["status"] == "success":
        request.session["successMessage"] = result["message"] 
        return JSONResponse(content={"redirect_url": "/?smtp_test_ok=true", "status": "success", "message": result["message"]})
    else:
        return JSONResponse(content=result)