import os
import subprocess
import zipfile
from lxml import etree
from io import BytesIO
import re
import shutil
from dotenv import load_dotenv

load_dotenv()
from helpers import replace_docx_placeholders_in_text

# --- Globale Konfiguration für Verzeichnisse ---
DOCX_TEMP_DIR = "temp_docx_processed"
PDF_GENERATED_DIR = "generated_pdfs"

# ========= ANPASSUNG STARTET HIER =========
# Der feste Windows-Pfad wird durch eine flexible Logik ersetzt.
# Er liest den Pfad aus einer Umgebungsvariable (für Windows)
# oder nimmt den Standard-Linux-Pfad (für die Cloud).
LIBREOFFICE_PATH = os.environ.get("LIBREOFFICE_PATH", "/usr/bin/libreoffice")
# ========= ANPASSUNG ENDE =========


# NEUE FUNKTION: Manipuliert die XML-Datei eines DOCX-Dokuments
def _manipulate_docx_xml_content(xml_content_bytes: bytes, data_row: dict) -> bytes:
    """
    Sucht und ersetzt Platzhalter in einem XML-Inhalt (z.B. document.xml, header.xml).
    """
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_content_bytes, parser)

    word_namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    
    for text_element in root.findall(f'.//{word_namespace}t'):
        original_text = text_element.text
        if original_text and '${' in original_text:
            new_text = replace_docx_placeholders_in_text(original_text, data_row)
            if new_text != original_text:
                text_element.text = new_text
    
    return etree.tostring(root, pretty_print=True, encoding='UTF-8', xml_declaration=True)


def generate_personalized_pdf(
    original_docx_path: str,
    data_row: dict,
    output_pdf_filename: str
) -> str:
    """
    Ersetzt Platzhalter in einer DOCX-Vorlage durch direkte XML-Manipulation
    und konvertiert sie dann mit LibreOffice zu PDF.
    Gibt den Pfad zur generierten PDF-Datei zurück.
    """
    if not os.path.exists(original_docx_path):
        raise FileNotFoundError(f"DOCX-Vorlage nicht gefunden: {original_docx_path}")

    temp_input_docx_path = os.path.join(DOCX_TEMP_DIR, f'temp_input_{os.urandom(8).hex()}.docx')
    temp_output_docx_path = os.path.join(DOCX_TEMP_DIR, f'temp_output_{os.urandom(8).hex()}.docx')
    
    try:
        shutil.copy(original_docx_path, temp_input_docx_path)

        with zipfile.ZipFile(temp_input_docx_path, 'r') as zin:
            with zipfile.ZipFile(temp_output_docx_path, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    file_content = zin.read(item.filename)

                    if item.filename == 'word/document.xml' or \
                       item.filename.startswith('word/header') and item.filename.endswith('.xml') or \
                       item.filename.startswith('word/footer') and item.filename.endswith('.xml'):
                        
                        modified_content = _manipulate_docx_xml_content(file_content, data_row)
                        zout.writestr(item, modified_content)
                    else:
                        zout.writestr(item, file_content)
        
    except Exception as e:
        if os.path.exists(temp_input_docx_path): os.unlink(temp_input_docx_path)
        if os.path.exists(temp_output_docx_path): os.unlink(temp_output_docx_path)
        raise Exception(f"Fehler bei der DOCX-XML-Manipulation: {e}")

    pdf_path = os.path.join(PDF_GENERATED_DIR, output_pdf_filename)
    
    libreoffice_command = [
        LIBREOFFICE_PATH, # Verwendet jetzt die flexible Variable
        "--headless",
        "--convert-to", "pdf",
        "--outdir", PDF_GENERATED_DIR,
        temp_output_docx_path
    ]
    
    try:
        # HINWEIS: Hier wird jetzt der try-Block um den subprocess.run herumgebaut,
        # um den FileNotFoundError spezifisch abzufangen, wie in Ihrem Originalcode.
        result = subprocess.run(libreoffice_command, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            # Hier geben wir eine detailliertere Fehlermeldung aus
            error_details = result.stderr or result.stdout
            raise Exception(f"LibreOffice Konvertierungsfehler ({result.returncode}): {error_details}")
        
        generated_pdf_filename_by_lo = os.path.basename(temp_output_docx_path).replace('.docx', '.pdf')
        actual_pdf_path_from_lo = os.path.join(PDF_GENERATED_DIR, generated_pdf_filename_by_lo)

        if not os.path.exists(actual_pdf_path_from_lo):
            raise Exception(f"LibreOffice Konvertierung fehlgeschlagen: PDF-Datei '{actual_pdf_path_from_lo}' nicht gefunden.")
        
        final_pdf_path = os.path.join(PDF_GENERATED_DIR, output_pdf_filename)
        if actual_pdf_path_from_lo != final_pdf_path:
            if os.path.exists(final_pdf_path):
                os.unlink(final_pdf_path)
            os.rename(actual_pdf_path_from_lo, final_pdf_path)
        else:
            final_pdf_path = actual_pdf_path_from_lo

        return final_pdf_path

    except subprocess.TimeoutExpired:
        raise Exception("LibreOffice Konvertierung hat zu lange gedauert und wurde abgebrochen (Timeout).")
    except FileNotFoundError:
        # Diese Fehlermeldung ist jetzt generischer und nicht mehr Windows-spezifisch.
        raise Exception(f"LibreOffice-Programm nicht gefunden unter dem Pfad '{LIBREOFFICE_PATH}'. "
                        "Bitte überprüfen Sie die Konfiguration (lokal in .env, in der Cloud im Code).")
    except Exception as e:
        raise Exception(f"Fehler bei LibreOffice-Aufruf: {e}")
    finally:
        if os.path.exists(temp_input_docx_path):
            os.unlink(temp_input_docx_path)
        if os.path.exists(temp_output_docx_path):
            os.unlink(temp_output_docx_path)