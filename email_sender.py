import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
from typing import Dict, List, Any
from datetime import datetime
import re

from settings_manager import get_smtp_settings
from sqlalchemy.orm import Session
from helpers import replace_docx_placeholders_in_text, replace_html_placeholders_in_text

async def send_personalized_emails(
    db: Session,
    user_id: int,
    sent_items_data: List[Dict[str, Any]],
    smtp_from_email: str
) -> List[Dict[str, str]]:
    """
    Sendet personalisierte E-Mails mit PDF-Anhängen.
    Gibt ein Protokoll der gesendeten/fehlgeschlagenen E-Mails zurück.
    """
    smtp_settings = get_smtp_settings(db, user_id)
    process_log = []

    if not smtp_settings:
        process_log.append({'status': 'error', 'message': "Fehler: Keine SMTP-Einstellungen für Ihren Account gefunden. Bitte unter 'Einstellungen' konfigurieren."})
        return process_log

    smtp_host = smtp_settings["host"]
    smtp_user = smtp_settings["user"]
    smtp_pass = smtp_settings["password"]
    smtp_port = int(smtp_settings["port"])
    smtp_secure = smtp_settings["secure"]

    if not sent_items_data:
        process_log.append({'status': 'error', 'message': 'Keine Dateien zum Senden ausgewählt.'})
        return process_log

    try:
        if smtp_secure == 'tls':
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.starttls()
        elif smtp_secure == 'ssl':
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        
        server.login(smtp_user, smtp_pass)

        sent_items_for_report = []

        for file_info in sent_items_data:
            try:
                msg = MIMEMultipart('alternative')
                sender_display_name = file_info.get('from_name') if file_info.get('from_name') else smtp_from_email.split('@')[0]
                msg['From'] = f"{sender_display_name} <{smtp_from_email}>"
                msg['To'] = file_info['recipient_email']
                msg['Subject'] = file_info['subject']

                html_email_body_template = file_info['body'] 
                html_body_processed = replace_html_placeholders_in_text(html_email_body_template, file_info['data_row'])

                plain_body_processed = re.sub(r'<[^>]+>', '', html_body_processed).strip()
                plain_body_processed = plain_body_processed.replace('</p>', '\n').replace('<p>', '')
                plain_body_processed = re.sub(r'\s+', ' ', plain_body_processed).strip()
                
                part1 = MIMEText(plain_body_processed, 'plain')
                part2 = MIMEText(html_body_processed, 'html')
                msg.attach(part1)
                msg.attach(part2)
                
                # GEÄNDERT: Anhang wird nur hinzugefügt, wenn ein PDF-Pfad vorhanden ist.
                pdf_path = file_info.get('pdf_path')
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        attach = MIMEApplication(f.read(), _subtype="pdf")
                        attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf_path))
                        msg.attach(attach)
                elif pdf_path and not os.path.exists(pdf_path):
                    # Wenn ein Anhang erwartet wurde, aber nicht gefunden wird -> Fehler
                    process_log.append({'status': 'error', 'message': f"Fehler: PDF für {file_info['recipient_email']} nicht gefunden: {os.path.basename(pdf_path)}."})
                    continue

                server.send_message(msg)
                process_log.append({'status': 'success', 'message': f"E-Mail erfolgreich an {file_info['recipient_email']} gesendet."})
                sent_items_for_report.append(file_info)

            except Exception as e:
                process_log.append({'status': 'error', 'message': f"Fehler beim Senden an {file_info['recipient_email']}: {e}"})

        server.quit()

        if sent_items_for_report:
            report_html = "<h1>Sendebestätigung</h1><p>Der Serienmail-Assistent hat am " + \
                      datetime.now().strftime(r'%d.%m.%Y \u\m %H:%M') + " Uhr E-Mails versendet:</p>"
            report_html += "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse; width: 100%;'>"
            # GEÄNDERT: Spalte für Dokument anpassen, um "Kein Anhang" zu zeigen
            report_html += "<tr><th style='background-color:#eee;'>Empfänger</th><th style='background-color:#eee;'>E-Mail</th><th style='background-color:#eee;'>Dokument</th></tr>"
            for report_item in sent_items_for_report:
                document_name = os.path.basename(report_item['pdf_path']) if report_item.get('pdf_path') else "Kein Anhang"
                report_html += f"<tr><td>{report_item['recipient_name']}</td><td>{report_item['recipient_email']}</td><td>{document_name}</td></tr>"
            report_html += "</table>"

            report_msg = MIMEMultipart('alternative')
            report_msg['From'] = f"Serienmail-Assistent Report <{smtp_from_email}>"
            report_msg['To'] = smtp_from_email
            report_msg['Subject'] = 'Protokoll: Serienmail-Versand'
            report_msg.attach(MIMEText(report_html, 'html'))
            
            try:
                if smtp_secure == 'tls':
                    report_server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                    report_server.starttls()
                elif smtp_secure == 'ssl':
                    report_server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
                else:
                    report_server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                
                report_server.login(smtp_user, smtp_pass)
                report_server.send_message(report_msg)
                report_server.quit()
                process_log.append({'status': 'info', 'message': f'Ein Sendeprotokoll wurde an {smtp_from_email} gesendet.'})
            except Exception as e:
                process_log.append({'status': 'error', 'message': f"Fehler beim Senden des Sendeprotokolls an {smtp_from_email}: {e}"})

    except Exception as e:
        process_log.append({'status': 'error', 'message': f"KRITISCHER FEHLER BEIM SENDEN (SMTP-Verbindung): {e}"})
    finally:
        pass

    return process_log