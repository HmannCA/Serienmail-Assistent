from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext

templates = Jinja2Templates(directory="templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")