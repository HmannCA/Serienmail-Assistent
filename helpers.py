import os
from datetime import datetime
import re
import html

# --- Hilfsfunktion, um Werte JSON-serialisierbar zu machen (insbesondere Datums-/Zeitwerte) ---
def clean_for_json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value

# --- Hilfsfunktion, um Platzhalter in DOCX-Text zu ersetzen ---
def replace_docx_placeholders_in_text(text: str, data_row: dict) -> str:
    """
    Ersetzt Platzhalter im Format ${Platzhalter} in einem Textstring durch Werte aus einer Datenzeile.
    """
    processed_text = text
    for key, value in data_row.items():
        replacement_value = str(value) if value is not None else ""
        processed_text = processed_text.replace(f'${{{key}}}', replacement_value)
    return processed_text

# --- Hilfsfunktion, um Platzhalter in HTML zu ersetzen ---
def replace_html_placeholders_in_text(template_html: str, data_row: dict) -> str:
    """
    Ersetzt Platzhalter im Format ${Platzhalter} in einem HTML-String durch Werte aus einer Datenzeile.
    Values werden HTML-escaped, um XSS zu verhindern.
    """
    processed_html = template_html
    for key, value in data_row.items():
        replacement_value = str(value) if value is not None else ""
        # html.escape() wird hier verwendet, um sicherzustellen, dass die ersetzten Werte keine XSS-Angriffe ermöglichen.
        # Es ist wichtig, dass die Platzhalter selbst nicht als HTML interpretiert werden.
        processed_html = processed_html.replace(f'${{{key}}}', html.escape(replacement_value))
    return processed_html