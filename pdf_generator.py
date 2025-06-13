import os
import subprocess
import zipfile
from lxml import etree
from io import BytesIO
import re
import shutil

from helpers import replace_docx_placeholders_in_text

# --- Globale Konfiguration für LibreOffice ---
# WICHTIG: Passe DIESEN Pfad an deinen LibreOffice-Installationspfad an!
LIBREOFFICE_PATH = r"F:\LibreOffice\program\soffice.exe" # Dein Pfad!

DOCX_TEMP_DIR = "temp_docx_processed"
PDF_GENERATED_DIR = "generated_pdfs"


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
        LIBREOFFICE_PATH,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", PDF_GENERATED_DIR,
        temp_output_docx_path
    ]
    
    try:
        result = subprocess.run(libreoffice_command, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            raise Exception(f"LibreOffice Konvertierungsfehler ({result.returncode}): {result.stderr}")
        
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
        raise Exception(f"LibreOffice-Programm nicht gefunden unter '{LIBREOFFICE_PATH}'. "
                        "Bitte überprüfen Sie den Pfad in pdf_generator.py und stellen Sie sicher, dass LibreOffice installiert ist.")
    except Exception as e:
        raise Exception(f"Fehler bei LibreOffice-Aufruf: {e}")
    finally:
        if os.path.exists(temp_input_docx_path):
            os.unlink(temp_input_docx_path)
        if os.path.exists(temp_output_docx_path):
            os.unlink(temp_output_docx_path)