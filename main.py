# Temporäre main.py zum Testen der Konfiguration
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"Status": "Die Minimal-App ist online!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}