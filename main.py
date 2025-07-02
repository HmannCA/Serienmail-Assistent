import os
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext
from fastapi.templating import Jinja2Templates
import traceback

from database import create_db_and_tables
from routers import auth as auth_router_module
from routers import main_app as main_app_router_module
from routers import settings as settings_router_module

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Serienbrief-Assistent")

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "super-secret-key-please-change")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
templates = Jinja2Templates(directory="templates")

# auth_router_module.set_global_templates_instance(templates)
# auth_router_module.set_global_pwd_context_instance(pwd_context)
# main_app_router_module.set_global_templates_instance(templates)
# settings_router_module.set_global_templates_instance(templates)

PDF_GENERATED_DIR = "generated_pdfs"
UPLOAD_DIR = "user_uploads"
for dir_path in [UPLOAD_DIR, os.path.join(UPLOAD_DIR, "word_templates"), PDF_GENERATED_DIR, "temp_docx_processed"]:
    os.makedirs(dir_path, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount(f"/{PDF_GENERATED_DIR}", StaticFiles(directory=PDF_GENERATED_DIR), name="generated_pdfs")

app.include_router(auth_router_module.router)
app.include_router(main_app_router_module.router)
app.include_router(settings_router_module.router)

@app.on_event("startup")
async def startup_event():
    create_db_and_tables()

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.headers and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=exc.status_code)
    if exc.status_code == 401:
        request.session["errorMessage"] = exc.detail
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(content=f"<h1>Fehler {exc.status_code}</h1><p>{exc.detail}</p>", status_code=exc.status_code)

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    error_traceback = traceback.format_exc()
    return HTMLResponse(content=f"<h1>Interner Serverfehler</h1><pre>{error_traceback}</pre>", status_code=500)