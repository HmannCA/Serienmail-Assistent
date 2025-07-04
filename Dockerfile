# Verwende ein offizielles Python-Basis-Image
FROM python:3.11-slim

# Setze das Arbeitsverzeichnis im Container
WORKDIR /app

# Verhindere, dass Python .pyc-Dateien schreibt
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# HIER IST DIE KORREKTUR:
# Der korrekte Paketname für eine Headless-Installation ist libreoffice-nogui
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libreoffice-nogui \
    && rm -rf /var/lib/apt/lists/*

# Kopiere die requirements.txt-Datei ZUERST in den Container
COPY requirements.txt .

# Installiere die Python-Pakete
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den Rest des Anwendungscodes in den Container
COPY . .

# Der Port, auf dem die App laufen wird (nur zur Information für Docker)
EXPOSE 8000

# Der Befehl zum Starten der App (wird durch die fly.toml überschrieben, ist aber ein guter Standard)
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]