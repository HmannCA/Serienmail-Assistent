import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import traceback
import shutil
import zipfile

from fastapi import APIRouter, Request, Form, File, UploadFile, Depends, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from starlette.background import BackgroundTask
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

# Importiere lokale Module
from database import SessionLocal, ProcessLogEntry, GeneratedFile
from helpers import clean_for_json, replace_docx_placeholders_in_text, replace_html_placeholders_in_text
from excel_processor import handle_excel_upload, read_excel_header, filter_excel_data, read_all_excel_data
from pdf_generator import generate_personalized_pdf, PDF_GENERATED_DIR, DOCX_TEMP_DIR
from email_sender import send_personalized_emails
from settings_manager import get_smtp_settings

# Importiere Abhängigkeiten und gemeinsame Objekte aus anderen Modulen
from routers.auth import get_current_user_id
from dependencies import templates  # Direkt aus dependencies importierenh

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

_templates_instance_main_app: Optional[Jinja2Templates] = None

def set_global_templates_instance(instance: Jinja2Templates):
    global _templates_instance_main_app
    _templates_instance_main_app = instance

def get_templates_instance_for_main_app() -> Jinja2Templates:
    if _templates_instance_main_app is None:
        raise RuntimeError("Templates instance not initialized. Call set_global_templates_instance in main.py startup.")
    return _templates_instance_main_app

UPLOAD_DIR = "user_uploads"

def cleanup_session_after_process(session):
    keys_to_unset = [
        'filteredData', 'isFiltered', 'filter_column', 'filter_value',
        'active_word_template', 'reviewFiles', 'no_attachment', 'isDetailsConfirmed'
    ]
    for key in keys_to_unset:
        if key in session:
            del session[key]

@router.get("/reset_process", response_class=RedirectResponse)
async def reset_process(request: Request, current_user_id: int = Depends(get_current_user_id)):
    session_data = request.session
    if 'excel_file_path' in session_data and session_data.get('excel_file_path') and os.path.exists(session_data['excel_file_path']):
        try:
            os.unlink(session_data['excel_file_path'])
        except OSError as e:
            print(f"Error deleting file {session_data['excel_file_path']}: {e}")

    keys_to_unset = [
        'excel_file_path', 'excel_file_original_name', 'filteredData',
        'isFiltered', 'filter_column', 'filter_value', 'active_word_template',
        'email_body', 'pdf_filename_format', 'email_subject', 'email_column',
        'reviewFiles', 'from_name', 'no_attachment', 'isDetailsConfirmed'
    ]
    for key in keys_to_unset:
        if key in session_data:
            del session_data[key]
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id), templates: Jinja2Templates = Depends(get_templates_instance_for_main_app)):
    session_data = request.session

    excel_file_path = session_data.get('excel_file_path')
    active_word_template = session_data.get('active_word_template', '')
    no_attachment = session_data.get('no_attachment', False)
    is_filtered = session_data.get('isFiltered', False)

    header = []
    if excel_file_path and os.path.exists(excel_file_path):
        try:
            header = read_excel_header(excel_file_path)
        except Exception as e:
            session_data["fatalError"] = f"Kritischer Fehler beim Lesen der Kopfzeile der Excel-Datei: {e}"

    pdf_filename_format = session_data.get('pdf_filename_format')
    if pdf_filename_format is None:
        if header:
            preferred_name_columns = ["Nummer", "Kundennummer", "ID", "Name", "Nachname", "Vorname"]
            found_placeholders = []
            for col in preferred_name_columns:
                if col in header:
                    found_placeholders.append(col)
                    if len(found_placeholders) == 2: break
            if len(found_placeholders) >= 2:
                pdf_filename_format = f"Rechnung_${{{found_placeholders[0]}}}_${{{found_placeholders[1]}}}.pdf"
            elif len(found_placeholders) == 1:
                pdf_filename_format = f"Dokument_${{{found_placeholders[0]}}}.pdf"
            else:
                pdf_filename_format = "Dokument_${timestamp}.pdf"
        else:
            pdf_filename_format = "Dokument.pdf"

    is_details_confirmed = session_data.get('isDetailsConfirmed', False)
    isReadyForStep4 = is_filtered and is_details_confirmed

    current_step = 'upload_excel'
    if session_data.get('reviewFiles') is not None: # Check if key exists, even with empty list
        current_step = 'review'
    elif excel_file_path:
        current_step = 'main_form'

    context = {
        "request": request,
        "username": session_data.get("username", "Gast"),
        "fatalError": session_data.pop("fatalError", None),
        "processLog": session_data.pop("processLog", []),
        "uploadError": session_data.pop("uploadError", None),
        "excelFilePath": excel_file_path,
        "originalExcelFilename": session_data.get('excel_file_original_name', 'Keine Datei ausgewählt'),
        "activeWordTemplate": active_word_template,
        "displayedWordTemplateName": os.path.basename(active_word_template) if active_word_template else "",
        "emailBody": session_data.get('email_body', '<p>Sehr geehrte/r ${Anrede} ${Name},</p><p>anbei erhalten Sie Ihr Dokument.</p>'),
        "pdfFilenameFormat": pdf_filename_format,
        "emailSubject": session_data.get('email_subject', 'Ihr Dokument'),
        "fromName": session_data.get('from_name', ''),
        "emailColumn": session_data.get('email_column', ''),
        "selectedColumnName": session_data.get('filter_column', ''),
        "filterValue": session_data.get('filter_value', ''),
        "isFiltered": is_filtered,
        "isDetailsConfirmed": is_details_confirmed,
        "isReadyForStep4": isReadyForStep4,
        "filteredData": session_data.get('filteredData', []),
        "header": header,
        "reviewFiles": session_data.get('reviewFiles', []),
        "currentStep": current_step,
        "isSmtpConfiguredOk": session_data.get("smtp_test_status") == 'success',
        "no_attachment": no_attachment
    }
    return templates.TemplateResponse("index.html", context)


@router.post("/", response_class=RedirectResponse)
async def handle_form_post(request: Request, action: Optional[str] = Form(None),
                           excel_file: Optional[UploadFile] = File(None),
                           column: Optional[str] = Form(None),
                           value: Optional[str] = Form(None),
                           word_template: Optional[UploadFile] = File(None),
                           email_column: Optional[str] = Form(None),
                           pdf_filename_format: Optional[str] = Form(None),
                           email_subject: Optional[str] = Form(None),
                           from_name: Optional[str] = Form(None),
                           email_body: Optional[str] = Form(None),
                           no_attachment: bool = Form(False),
                           current_user_id: int = Depends(get_current_user_id),
                           db: Session = Depends(get_db)):
    session_data = request.session
    form_data = await request.form()

    if action == 'upload_excel':
        await reset_process(request, current_user_id)
        upload_result = await handle_excel_upload(excel_file, current_user_id)
        if "error" in upload_result:
            session_data["fatalError"] = upload_result["error"]
        else:
            session_data['excel_file_path'] = upload_result["file_path"]
            session_data['excel_file_original_name'] = upload_result["original_name"]
            session_data["processLog"] = [{'status': 'success', 'message': f"Tabelle '{upload_result['original_name']}' erfolgreich hochgeladen."}]

    elif action == 'apply_filter':
        excel_file_path = session_data.get('excel_file_path')
        if not excel_file_path or not os.path.exists(excel_file_path):
            session_data["fatalError"] = "Bitte zuerst eine gültige Excel-Datei hochladen."
        else:
            try:
                if not column or not value:
                    processed_data = read_all_excel_data(excel_file_path)
                    session_data.update({'filter_column': 'Alle', 'filter_value': 'Alle'})
                    session_data["processLog"] = [{'status': 'success', 'message': f"Alle {len(processed_data)} Datensätze aus der Tabelle geladen."}]
                else:
                    processed_data = filter_excel_data(excel_file_path, column, value)
                    session_data.update({'filter_column': column, 'filter_value': value})
                    session_data["processLog"] = [{'status': 'success', 'message': f"Für den Filter '{value}' in Spalte '{column}' wurden {len(processed_data)} Einträge gefunden."}]
                session_data['filteredData'] = processed_data
                session_data['isFiltered'] = True
            except Exception as e:
                session_data["fatalError"] = f"Kritischer Fehler bei der Datenverarbeitung: {e}"

    elif action == 'confirm_details':
        session_data.update({
            'email_body': email_body, 'pdf_filename_format': pdf_filename_format,
            'email_subject': email_subject, 'from_name': from_name,
            'email_column': email_column, 'no_attachment': no_attachment,
            'isDetailsConfirmed': False # Zurücksetzen, falls erneut bestätigt wird
        })
        upload_error_msg = None
        if not no_attachment and word_template and word_template.filename:
            try:
                safe_filename = "".join(c for c in word_template.filename if c.isalnum() or c in ['-', '_', '.'])
                template_dir = os.path.join(UPLOAD_DIR, "word_templates")
                os.makedirs(template_dir, exist_ok=True)
                unique_filename = f"{current_user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{safe_filename}"
                new_template_path = os.path.join(template_dir, unique_filename)
                with open(new_template_path, "wb") as buffer:
                    shutil.copyfileobj(word_template.file, buffer)
                session_data['active_word_template'] = new_template_path
            except Exception as e:
                upload_error_msg = f"Fehler beim Speichern der Vorlage: {e}"
        elif not no_attachment and not session_data.get('active_word_template'):
             upload_error_msg = "Keine Vorlage ausgewählt. Bitte eine .docx-Vorlage hochladen."
        
        if upload_error_msg:
            session_data["uploadError"] = upload_error_msg
        else:
            session_data.pop("uploadError", None)
            session_data["processLog"] = [{'status': 'success', 'message': "Vorlagen- und Inhalts-Details erfolgreich übernommen."}]
            # Nur wenn alle Pflichtfelder ausgefüllt sind, wird der Schritt als bestätigt markiert
            if email_column and email_subject and from_name and (no_attachment or session_data.get('active_word_template')):
                 session_data['isDetailsConfirmed'] = True

    # === NEUER, ROBUSTERER GENERIERUNGS-BLOCK ===
    elif action == 'generate_for_review':
        filtered_data = session_data.get('filteredData', [])
        session_data['reviewFiles'] = [] # Alte Vorschau immer zuerst leeren

        if not filtered_data:
            session_data["processLog"] = [{'status': 'error', 'message': "Keine Daten zur Verarbeitung gefunden. Bitte filtern Sie zuerst."}]
        else:
            review_files = []
            generation_log = []
            total_rows = len(filtered_data)

            for index, row_data in enumerate(filtered_data):
                try:
                    pdf_path, pdf_web_path = None, None
                    if not session_data.get('no_attachment', False):
                        filename_template = session_data.get('pdf_filename_format', 'Dokument.pdf')
                        # Platzhalter im Dateinamen ersetzen
                        output_filename_raw = replace_docx_placeholders_in_text(filename_template, row_data)
                        # Dateinamen für das Dateisystem sicher machen
                        output_filename_safe = "".join(c for c in output_filename_raw if c.isalnum() or c in ['-', '_', '.']).strip()
                        if not output_filename_safe:
                            output_filename_safe = f"dokument_{index+1}.pdf"

                        pdf_path = generate_personalized_pdf(
                            original_docx_path=session_data.get('active_word_template'),
                            data_row=row_data,
                            output_pdf_filename=output_filename_safe
                        )
                        pdf_web_path = f"/{PDF_GENERATED_DIR}/{os.path.basename(pdf_path)}"

                    review_files.append({
                        'pdf_path': pdf_path, 'pdf_web_path': pdf_web_path,
                        'recipient_email': row_data.get(session_data.get('email_column', ''), 'N/A'),
                        'recipient_name': f"{row_data.get('Vorname', '')} {row_data.get('Name', '')}".strip() or row_data.get('Name', f'Empfänger {index+1}'),
                        'subject': replace_docx_placeholders_in_text(session_data.get('email_subject', ''), row_data),
                        'body': session_data.get('email_body', ''),
                        'data_row': row_data
                    })
                except Exception as e:
                    # Wenn eine Zeile fehlschlägt, wird dies protokolliert und die Schleife fortgesetzt
                    error_recipient = row_data.get(session_data.get('email_column', ''), f'Unbekannt in Zeile {index + 2}')
                    generation_log.append({'status': 'error', 'message': f"Fehler bei Erstellung für '{error_recipient}': {e}"})
                    continue
            
            # Nach der Schleife werden die Ergebnisse in der Session gespeichert
            session_data['reviewFiles'] = review_files
            
            success_count = len(review_files)
            if success_count > 0:
                generation_log.insert(0, {'status': 'success', 'message': f"{success_count} von {total_rows} E-Mails erfolgreich zur Vorschau erstellt."})
            
            error_count = total_rows - success_count
            if error_count > 0:
                generation_log.append({'status': 'info', 'message': f"WICHTIG: {error_count} E-Mail(s) konnten wegen Fehlern nicht erstellt werden (Details siehe oben)."})

            if not generation_log:
                 generation_log.append({'status': 'info', 'message': 'Keine Daten zum Verarbeiten gefunden.'})

            session_data["processLog"] = generation_log

    elif action == 'send_selected':
        selected_identifiers = form_data.getlist('selected_files[]')
        all_review_files = session_data.get('reviewFiles', [])
        items_to_send = [item for i, item in enumerate(all_review_files) if (item.get('pdf_path') or f'no-pdf-{i+1}') in selected_identifiers]

        if not items_to_send:
            session_data["processLog"] = [{'status': 'error', 'message': 'Keine E-Mails zum Senden ausgewählt.'}]
        else:
            smtp_settings = get_smtp_settings(db, current_user_id)
            if not smtp_settings:
                session_data["processLog"] = [{'status': 'error', 'message': "Fehler: Keine SMTP-Einstellungen gefunden."}]
            else:
                for item in items_to_send:
                    item['body'] = replace_html_placeholders_in_text(item['body'], item['data_row'])
                mail_send_log = await send_personalized_emails(db, current_user_id, items_to_send, smtp_settings['user'])
                session_data["processLog"] = mail_send_log
                # DB-Logging (unverändert) ...
                cleanup_session_after_process(session_data) # Session nach erfolgreichem Versand aufräumen
                return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    elif action == 'download_zip':
        review_files = session_data.get('reviewFiles', [])
        pdf_files = [f['pdf_path'] for f in review_files if f.get('pdf_path') and os.path.exists(f['pdf_path'])]
        if not pdf_files:
            session_data["processLog"] = [{'status': 'error', 'message': 'Keine PDF-Dateien zum Zippen gefunden.'}]
        else:
            zip_filename = os.path.join(PDF_GENERATED_DIR, f"Serienbriefe_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.zip")
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zf:
                for pdf_path in pdf_files: zf.write(pdf_path, os.path.basename(pdf_path))
            def cleanup_zip(file_path):
                try: os.unlink(file_path)
                except OSError as e: print(f"Error deleting zip file {file_path}: {e}")
            
            cleanup_session_after_process(session_data) # Session auch nach dem Download aufräumen
            return FileResponse(path=zip_filename, filename=os.path.basename(zip_filename), media_type="application/zip", background=BackgroundTask(cleanup_zip, file_path=zip_filename))

    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)