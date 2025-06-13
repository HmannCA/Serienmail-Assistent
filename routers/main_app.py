import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import traceback
import shutil
import zipfile

from fastapi import APIRouter, Request, Form, File, UploadFile, Depends, status, HTTPException 
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates 

from sqlalchemy.orm import Session 

# Importiere lokale Module
from database import SessionLocal, ProcessLogEntry, GeneratedFile 
from helpers import clean_for_json, replace_docx_placeholders_in_text, replace_html_placeholders_in_text 
from excel_processor import handle_excel_upload, read_excel_header, filter_excel_data
from pdf_generator import generate_personalized_pdf, PDF_GENERATED_DIR, DOCX_TEMP_DIR 
from email_sender import send_personalized_emails
from settings_manager import get_smtp_settings 

# Importiere Abhängigkeiten und gemeinsame Objekte aus anderen Modulen
from routers.auth import get_current_user_id 
# Wir importieren get_templates_instance von auth, da es das globale Setter/Getter für templates ist.
from routers.auth import get_templates_instance as get_templates_instance_from_auth # Umbenannt für Klarheit


router = APIRouter()

# Datenbank-Abhängigkeit
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Abhängigkeit für templates (Hier bleibt die Referenz zur globalen Instanz)
# Dies ist der Provider für diesen Router.
# Die globale Instanz wird über get_templates_instance_from_auth geholt.
_templates_instance_main_app: Optional[Jinja2Templates] = None 

def set_global_templates_instance(instance: Jinja2Templates): # DIESE FUNKTION WIRD HINZUGEFÜGT
    global _templates_instance_main_app
    _templates_instance_main_app = instance

def get_templates_instance_for_main_app() -> Jinja2Templates: 
    if _templates_instance_main_app is None:
        raise RuntimeError("Templates instance not initialized. Call set_global_templates_instance in main.py startup.")
    return _templates_instance_main_app


# Pfade für Uploads (Müssen hier definiert sein, da sie direkt im Modul verwendet werden)
UPLOAD_DIR = "user_uploads"


@router.get("/reset_process", response_class=RedirectResponse)
async def reset_process(request: Request, current_user_id: int = Depends(get_current_user_id)):
    session_data = request.session
    if 'excel_file_path' in session_data and os.path.exists(session_data['excel_file_path']):
        os.unlink(session_data['excel_file_path'])
    session_keys_to_unset = ['excel_file_path', 'excel_file_original_name', 'filteredData',
                             'isFiltered', 'filter_column', 'filter_value', 'active_word_template',
                             'email_body', 'pdf_filename_format', 'email_subject', 'email_column',
                             'reviewFiles', 'from_name', 'smtp_tested_ok'] 
    for key in session_keys_to_unset:
        if key in session_data:
            del session_data[key]
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id), templates: Jinja2Templates = Depends(get_templates_instance_for_main_app)): 
    """Hauptseite des Assistenten."""
    session_data = request.session 
    
    username = session_data.get("username", "Gast") 

    fatal_error = session_data.pop("fatalError", None)
    process_log = session_data.pop("processLog", [])
    upload_error = session_data.pop("uploadError", None)

    excel_file_path = session_data.get('excel_file_path')
    original_excel_filename = session_data.get('excel_file_original_name', 'Keine Datei ausgewählt')
    active_word_template = session_data.get('active_word_template', '') 
    email_body = session_data.get('email_body', 'Sehr geehrte ${Anrede}, ') 
    pdf_filename_format = session_data.get('pdf_filename_format') 
    email_subject = session_data.get('email_subject', 'Ihre Dokumente') 
    from_name = session_data.get('from_name', '') 
    email_column = session_data.get('email_column', '') 
    selected_column_name = session_data.get('filter_column', None) 
    filter_value = session_data.get('filter_value', '') 
    is_filtered = session_data.get('isFiltered', False) 
    filtered_data = session_data.get('filteredData', []) 
    
    review_files = session_data.get('reviewFiles', []) 


    header = []
    if excel_file_path and os.path.exists(excel_file_path):
        try:
            header = read_excel_header(excel_file_path)
        except Exception as e:
            fatal_error = f"Kritischer Fehler beim Lesen der Kopfzeile der Excel-Datei: {e}"
            session_data["fatalError"] = fatal_error

    # --- Dynamische Bestimmung des PDF-DateiNamens-Vorschlags ---
    preferred_name_columns = ["Nummer", "Kundennummer", "ID", "Name", "Nachname", "Vorname"]
    
    generated_pdf_filename_format = "${Nummer}_${Name}.pdf" # Fallback-Standard

    if pdf_filename_format is None: 
        if header:
            found_placeholders = []
            for col in preferred_name_columns:
                if col in header:
                    found_placeholders.append(col)
                    if len(found_placeholders) == 2: 
                        break
            
            if len(found_placeholders) >= 2:
                generated_pdf_filename_format = f"${{{found_placeholders[0]}}}_${{{found_placeholders[1]}}}.pdf"
            elif len(found_placeholders) == 1:
                 generated_pdf_filename_format = f"${{{found_placeholders[0]}}}.pdf"
            else: 
                generated_pdf_filename_format = "Dokument_${timestamp}.pdf"
        else: 
            generated_pdf_filename_format = "Dokument_${timestamp}.pdf"
    else: 
        generated_pdf_filename_format = pdf_filename_format

    # --- ENDE: Dynamische Bestimmung des PDF-DateiNamens-Vorschlags ---

    current_step = None
    if 'step' in request.query_params and request.query_params['step'] == 'review': 
        current_step = 'review'
    elif 'step' in request.query_params and request.query_params['step'] == 'main_form': 
        current_step = 'main_form'
    elif not excel_file_path:
        current_step = 'upload_excel'
    else:
        current_step = 'main_form'

    # NEU: Definition von isReadyForStep3 vor der Highlight-Logik
    isReadyForStep3 = is_filtered and bool(active_word_template) and bool(email_column)

    # --- NEUE LOGIK FÜR highlight_field_id (Scroll-Ziel und Highlight) ---
    highlight_field_id = None
    scroll_behavior = 'smooth'
    scroll_block = 'nearest' # Default für die meisten Felder

    # last_action von Session holen, die im POST gesetzt wurde
    last_action_in_session = session_data.get('last_action', None) 
    # Und die last_action in der Session nach dem Auslesen des GET-Requests leeren,
    # damit der Scroll-Trigger nur einmal ausgelöst wird.
    if 'last_action' in session_data: 
        del session_data['last_action'] 


    if current_step == 'upload_excel':
        highlight_field_id = 'excel_file_upload_container'
        scroll_block = 'start' 
    elif current_step == 'main_form':
        if is_filtered and not isReadyForStep3 and last_action_in_session == 'filter_data':
            highlight_field_id = 'placeholders_card' 
            scroll_block = 'start'
        elif not selected_column_name:
            highlight_field_id = 'column_select'
        elif not filter_value:
            highlight_field_id = 'value_input'
        elif isReadyForStep3 and last_action_in_session == 'confirm_templates':
            highlight_field_id = 'generate_for_review_button' 
            scroll_block = 'center'
        elif is_filtered and not active_word_template:
            highlight_field_id = 'word_template_upload_container'
        elif active_word_template and not email_column:
            highlight_field_id = 'email_column_select'
        elif active_word_template and email_column: 
            if not generated_pdf_filename_format or generated_pdf_filename_format == "Dokument_${timestamp}.pdf":
                highlight_field_id = 'pdf_filename_format'
            elif not email_subject:
                highlight_field_id = 'email_subject'
            elif not from_name:
                highlight_field_id = 'from_name'
            elif not email_body or email_body.strip() == 'Sehr geehrte ${Anrede},':
                highlight_field_id = 'editor'
            else: 
                highlight_field_id = 'confirm_templates_button'
    
    # --- ENDE NEUE LOGIK FÜR highlight_field_id ---

    # Anpassung des angezeigten Dateinamens der Word-Vorlage
    displayed_word_template_name = ""
    if active_word_template:
        displayed_word_template_name = os.path.basename(active_word_template) 

    # NEU: SMTP-Teststatus für das Template
    smtp_test_status = session_data.get("smtp_test_status")
    is_smtp_configured_ok = (smtp_test_status == 'success')


    context = {
        "request": request,
        "username": username,
        "fatalError": fatal_error,
        "processLog": process_log,
        "uploadError": upload_error,
        "excelFilePath": excel_file_path,
        "originalExcelFilename": original_excel_filename,
        "activeWordTemplate": active_word_template, 
        "displayedWordTemplateName": displayed_word_template_name, 
        "emailBody": email_body,
        "pdfFilenameFormat": generated_pdf_filename_format, 
        "emailSubject": email_subject,
        "fromName": from_name,
        "emailColumn": email_column,
        "selectedColumnName": selected_column_name,
        "filterValue": filter_value,
        "isFiltered": is_filtered,
        "filteredData": filtered_data,
        "header": header,
        "reviewFiles": review_files,
        "currentStep": current_step,
        "isReadyForStep3": isReadyForStep3, 
        "highlight_field_id": highlight_field_id,
        "scroll_block_param": scroll_block,
        "isSmtpConfiguredOk": is_smtp_configured_ok 
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
                           current_user_id: int = Depends(get_current_user_id),
                           db: Session = Depends(get_db)): 
    session_data = request.session
    form_data = await request.form() 

    session_data['last_action'] = action 

    smtp_test_status = session_data.get("smtp_test_status")
    if smtp_test_status != 'success' and action != 'reset_process':
        session_data["errorMessage"] = "Bitte testen Sie zuerst erfolgreich Ihre SMTP-Einstellungen, bevor Sie den Serienmail-Assistenten nutzen."
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


    # Korrigierte Einrückung für if/elif Kette beginnt hier
    if action == 'upload_excel':
        upload_result = await handle_excel_upload(excel_file, current_user_id)
        if "error" in upload_result:
            session_data["fatalError"] = upload_result["error"]
        else:
            session_data['excel_file_path'] = upload_result["file_path"]
            session_data['excel_file_original_name'] = upload_result["original_name"]

            if 'pdf_filename_format' in session_data:
                del session_data['pdf_filename_format'] 

            session_keys_to_unset = ['filteredData', 'isFiltered', 'filter_column', 'filter_value',
                                     'active_word_template', 'from_name']
            for key in session_keys_to_unset:
                if key in session_data:
                    del session_data[key]
            session_data["processLog"] = [
                {'status': 'success', 'message': f"Tabelle '{upload_result['original_name']}' erfolgreich hochgeladen."}
            ]
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    elif action == 'filter_data':
        selected_column_name_for_filter = column
        filter_value_for_filter = value
        excel_file_path_for_filter = session_data.get('excel_file_path')

        try:
            temp_filtered_data = filter_excel_data(excel_file_path_for_filter,
                                                   selected_column_name_for_filter,
                                                   filter_value_for_filter)
            session_data['filteredData'] = temp_filtered_data
            session_data['isFiltered'] = True
            session_data['filter_column'] = selected_column_name_for_filter
            session_data['filter_value'] = filter_value_for_filter

            session_data["processLog"] = [
                {'status': 'success', 'message': f"Für den Filter '{filter_value_for_filter}' in Spalte '{selected_column_name_for_filter}' wurden {len(temp_filtered_data)} Einträge gefunden."}
            ]
        except Exception as e:
            session_data["fatalError"] = f"Kritischer Fehler beim Filtern der Daten: {e}"

        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    elif action == 'confirm_templates':
        upload_error_msg = None
        if word_template and word_template.filename:
            file_info = os.path.splitext(word_template.filename)
            extension = file_info[1].lower()
            if extension == '.docx':
                safe_filename = "".join(c for c in word_template.filename if c.isalnum() or c in ['-', '_', '.'])
                template_dir = os.path.join(UPLOAD_DIR, "word_templates")
                if not os.path.exists(template_dir):
                    os.makedirs(template_dir)
                new_template_path = os.path.join(template_dir, safe_filename)
                try:
                    with open(new_template_path, "wb") as buffer:
                        shutil.copyfileobj(word_template.file, buffer)
                    session_data['active_word_template'] = new_template_path
                    session_data["processLog"] = [
                        {'status': 'success', 'message': f"Word-Vorlage '{word_template.filename}' erfolgreich hochgeladen."}
                    ]
                except Exception as e:
                    upload_error_msg = f"Fehler beim Speichern der Vorlage: {e}"
            else:
                upload_error_msg = "Ungültiges Dateiformat. Bitte .docx hochladen."
        elif not session_data.get('active_word_template'):
            upload_error_msg = "Keine Vorlage ausgewählt."
        
        if upload_error_msg:
            session_data["uploadError"] = upload_error_msg
            session_data["processLog"] = [{'status': 'error', 'message': upload_error_msg}]
        else:
            session_data["processLog"] = [
                {'status': 'success', 'message': "E-Mail-Details erfolgreich übernommen."}
            ]

        session_data['email_body'] = email_body
        session_data['pdf_filename_format'] = pdf_filename_format 
        session_data['email_subject'] = email_subject
        session_data['from_name'] = from_name
        session_data['email_column'] = email_column

        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    elif action == 'generate_for_review':

        filtered_data = session_data.get('filteredData', [])
        active_word_template = session_data.get('active_word_template')
        pdf_filename_format = session_data.get('pdf_filename_format') 
        email_column = session_data.get('email_column', '')
        email_subject_template = session_data.get('email_subject', 'Ihre Dokumente')
        email_body_template = email_body 
        from_name = session_data.get('from_name', '')

        if not pdf_filename_format:
            pdf_filename_format = "Dokument_${timestamp}.pdf"

        if not filtered_data:
            session_data["processLog"] = [{'status': 'error', 'message': "Keine gefilterten Daten zum Erzeugen von PDFs."}]
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        if not active_word_template or not os.path.exists(active_word_template):
            session_data["processLog"] = [{'status': 'error', 'message': "Keine aktive Word-Vorlage gefunden oder Vorlage nicht vorhanden."}]
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        if not email_column:
            session_data["processLog"] = [{'status': 'error', 'message': "Bitte wählen Sie die Spalte mit den E-Mail-Adressen aus."}]
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

        review_files = []
        
        try:
            for i, row_data in enumerate(filtered_data):
                generated_pdf_path = generate_personalized_pdf(
                    original_docx_path=active_word_template,
                    data_row=row_data,
                    output_pdf_filename=replace_docx_placeholders_in_text(pdf_filename_format, row_data)
                )

                recipient_email = row_data.get(email_column, 'N/A')
                recipient_name = f"{row_data.get('Vorname', '')} {row_data.get('Name', '')}".strip()
                if not recipient_name:
                    recipient_name = row_data.get('Name', 'Unbekannt')

                review_files.append({
                    'pdf_path': generated_pdf_path,
                    'pdf_web_path': f"/{PDF_GENERATED_DIR}/{os.path.basename(generated_pdf_path)}", 
                    'recipient_email': recipient_email,
                    'recipient_name': recipient_name,
                    'subject': replace_docx_placeholders_in_text(email_subject_template, row_data),
                    'body': replace_html_placeholders_in_text(email_body_template, row_data), 
                    'from_name': from_name,
                    'data_row': row_data 
                })

            session_data['reviewFiles'] = review_files 
            session_data['processLog'] = [{'status': 'success', 'message': f"{len(review_files)} PDF-Dokumente erfolgreich zur Vorschau erstellt."}]
            return RedirectResponse(url="/?step=review", status_code=status.HTTP_302_FOUND)

        except Exception as e:
            session_data["processLog"] = [{'status': 'error', 'message': f"KRITISCHER FEHLER bei der PDF-Erzeugung: {e}"}]
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    elif action == 'send_selected': 
        print("DEBUG (main_app.py): Aktion 'send_selected' gestartet.")
        selected_files_from_form = form_data.getlist('selected_files[]')

        if not selected_files_from_form:
            session_data["processLog"] = [{'status': 'error', 'message': 'Keine Dateien zum Senden ausgewählt.'}]
        else:
            all_review_files = session_data.get('reviewFiles', [])

            selected_file_basenames = [os.path.basename(f) for f in selected_files_from_form]

            sent_items_for_email_send = [
                item for item in all_review_files if os.path.basename(item['pdf_path']) in selected_file_basenames
            ]

            if not sent_items_for_email_send:
                session_data["processLog"] = [{'status': 'error', 'message': 'Ausgewählte Dateien konnten nicht für den Versand gefunden werden.'}]
            else:
                try:
                    db_session_for_send = get_db().__next__()
                    smtp_settings = get_smtp_settings(db_session_for_send, current_user_id)
                    db_session_for_send.close()
                    
                    if not smtp_settings:
                        session_data["processLog"] = [{'status': 'error', 'message': "Fehler: Keine SMTP-Einstellungen für Ihren Account gefunden. Bitte unter 'Einstellungen' konfigurieren."}]
                    else:
                        db_session_for_email_sender = get_db().__next__()
                        mail_send_log = await send_personalized_emails(
                            db=db_session_for_email_sender,
                            user_id=current_user_id,
                            sent_items_data=sent_items_for_email_send,
                            smtp_from_email=smtp_settings['user']
                        )
                        db_session_for_email_sender.close()

                        session_data["processLog"] = mail_send_log

                        print("DEBUG (main_app.py): Starte Historie-Speicherung für 'send_selected'.")
                        try:
                            excel_name = session_data.get('excel_file_original_name', 'Unbekannt')
                            word_template_name = os.path.basename(session_data.get('active_word_template', '') if session_data.get('active_word_template') else 'Unbekannt')
                            
                            process_entry = ProcessLogEntry(
                                user_id=current_user_id,
                                timestamp=datetime.utcnow(),
                                excel_file_original_name=excel_name,
                                word_template_original_name=word_template_name,
                                filter_column=session_data.get('filter_column', 'N/A'),
                                filter_value=session_data.get('filter_value', 'N/A'),
                                email_subject_template=session_data.get('email_subject', 'N/A'),
                                email_body_template=session_data.get('email_body', 'N/A'),
                                from_name=session_data.get('from_name', 'N/A'),
                                total_recipients=len(session_data.get('filteredData', [])),
                                sent_emails_count=len([log for log in mail_send_log if log['status'] == 'success']),
                                status='completed' if all(log['status'] == 'success' for log in mail_send_log) else 'partial_success' if any(log['status'] == 'success' for log in mail_send_log) else 'failed'
                            )
                            db.add(process_entry)
                            db.flush() 

                            for item in sent_items_for_email_send:
                                item_log = next((log for log in mail_send_log if log.get('message') and item['recipient_email'] in log['message']), None)
                                email_status = item_log['status'] if item_log else 'unknown'
                                email_message = item_log['message'] if item_log else 'No specific log message.'

                                generated_file_entry = GeneratedFile(
                                    process_id=process_entry.id,
                                    recipient_email=item['recipient_email'],
                                    recipient_name=item['recipient_name'],
                                    pdf_filename=os.path.basename(item['pdf_path']),
                                    pdf_storage_path=item['pdf_path'], 
                                    email_sent_status=email_status,
                                    email_sent_message=email_message,
                                    sent_timestamp=datetime.utcnow() if email_status == 'success' else None
                                )
                                db.add(generated_file_entry)
                            
                            db.commit()
                            print("DEBUG (main_app.py): Historie-Einträge für 'send_selected' erfolgreich committet.")

                        except Exception as e:
                            db.rollback()
                            print(f"FEHLER (main_app.py): Fehler beim Speichern der Historie für 'send_selected': {e}")
                            session_data["processLog"].append({'status': 'error', 'message': f"Fehler beim Speichern der Vorgangshistorie: {e}"})

                        for item in sent_items_for_email_send:
                            if os.path.exists(item['pdf_path']):
                                os.unlink(item['pdf_path'])

                        session_keys_to_unset = ['reviewFiles', 'filteredData', 'isFiltered', 'filter_column', 'filter_value', 'active_word_template', 'from_name']
                        for key in session_keys_to_unset:
                            if key in session_data:
                                del session_data[key]

                except Exception as e:
                    db.rollback() 
                    session_data["processLog"] = [{'status': 'error', 'message': f"KRITISCHER FEHLER BEIM VERSAND-PROZESS: {e}"}]
                    print(f"FEHLER (main_app.py): Kritischer Fehler beim E-Mail-Versand-Prozess: {e}") 

            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    elif action == 'download_zip':
        print("DEBUG (main_app.py): Aktion 'download_zip' gestartet.")
        review_files = session_data.get('reviewFiles', [])

        if not review_files:
            session_data["processLog"] = [{'status': 'error', 'message': 'Keine Dateien zum Zippen gefunden.'}]
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

        zip_filename = os.path.join(PDF_GENERATED_DIR, f"Serienbriefe_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.zip")
        
        try:
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_info in review_files:
                    if os.path.exists(file_info['pdf_path']):
                        zf.write(file_info['pdf_path'], os.path.basename(file_info['pdf_path']))
                        print(f"DEBUG: handle_form_post - Added to zip: {file_info['pdf_path']}")
            
            for file_info in review_files:
                if os.path.exists(file_info['pdf_path']):
                    os.unlink(file_info['pdf_path'])
                    print(f"DEBUG: handle_form_post - Deleted zipped PDF: {file_info['pdf_path']}")

            session_keys_to_unset = ['reviewFiles', 'filteredData', 'isFiltered', 'filter_column', 'filter_value', 'active_word_template', 'from_name']
            for key in session_keys_to_unset:
                if key in session_data:
                    del session_data[key]
                    print(f"DEBUG: handle_form_post - Session key '{key}' unset after zip.")
            
            return FileResponse(path=zip_filename, filename=os.path.basename(zip_filename), media_type="application/zip")

        except Exception as e:
            session_data["processLog"] = [{'status': 'error', 'message': f"Fehler beim Erstellen des ZIP-Archivs: {e}"}]
            print(f"DEBUG: handle_form_post - CRITICAL ERROR during zip creation: {e}")
            print(traceback.format_exc())
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


    # DIESER BLOCK MUSS AUF DER GLEICHEN EBENE WIE DIE 'if' UND 'elif' ANWEISUNGEN SEIN.
    # Wenn er zu stark eingerückt ist, führt das zu einem SyntaxError,
    # weil er nicht mehr Teil der if/elif-Kette ist.
    session_data["processLog"] = [{'status': 'error', 'message': f"Unbekannte Aktion oder fehlende Daten für Aktion '{action}'. Fokus auf Einrückung."}]
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)