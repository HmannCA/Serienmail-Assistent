from fastapi import APIRouter, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from dependencies import templates
from database import SessionLocal
from settings_manager import save_smtp_settings, get_smtp_settings
from routers.auth import get_current_user_id
from utils.smtp_test_utils import test_smtp_connection_internal

router = APIRouter()

def get_db():
    db = SessionLocal(); yield db; db.close()

@router.get("/settings", response_class=HTMLResponse)
async def get_settings_form(request: Request, db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id)):
    settings = get_smtp_settings(db, current_user_id) or {}
    context = {
        "request": request,
        "smtp_host": settings.get("host", ""),
        "smtp_user": settings.get("user", ""),
        "smtp_pass": settings.get("password", ""),
        "smtp_port": settings.get("port", "587"),
        "smtp_secure": settings.get("secure", "tls"),
        "successMessage": request.session.pop("successMessage", None),
        "errorMessage": request.session.pop("errorMessage", None),
    }
    return templates.TemplateResponse("settings.html", context)

@router.post("/settings", response_class=RedirectResponse)
async def post_settings(request: Request, smtp_host: str = Form(...), smtp_user: str = Form(...), smtp_pass: str = Form(...), smtp_port: str = Form(...), smtp_secure: str = Form(...), db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id)):
    try:
        save_smtp_settings(db, current_user_id, smtp_host, smtp_user, smtp_pass, smtp_port, smtp_secure)
        
        # === HIER IST DIE KORREKTUR: smtp_user wird als Test-Empfänger übergeben ===
        test_result = await test_smtp_connection_internal(host=smtp_host, user=smtp_user, password=smtp_pass, port=smtp_port, secure=smtp_secure, test_recipient_email=smtp_user, send_test_email=True)
        
        request.session["smtp_test_status"] = test_result["status"]
        if test_result["status"] == "success":
            request.session["successMessage"] = "Einstellungen gespeichert und Verbindung erfolgreich getestet!"
        else:
            request.session["errorMessage"] = f"Gespeichert, aber Test fehlgeschlagen: {test_result['message']}"
    except Exception as e:
        request.session["errorMessage"] = f"Fehler beim Speichern: {e}"
    
    return RedirectResponse(url="/settings", status_code=status.HTTP_302_FOUND)

@router.post("/settings/test-smtp", response_class=JSONResponse)
async def test_smtp_connection_endpoint(smtp_host: str = Form(...), smtp_user: str = Form(...), smtp_pass: str = Form(...), smtp_port: str = Form(...), smtp_secure: str = Form(...)):
    
    # === HIER IST DIE KORREKTUR: smtp_user wird als Test-Empfänger übergeben ===
    result = await test_smtp_connection_internal(host=smtp_host, user=smtp_user, password=smtp_pass, port=smtp_port, secure=smtp_secure, test_recipient_email=smtp_user, send_test_email=True)
    return JSONResponse(content=result)