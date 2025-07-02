import os
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, UniqueConstraint, DateTime, Boolean, DECIMAL
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta 
from dotenv import load_dotenv

# Lade Umgebungsvariablen aus .env-Datei
load_dotenv()

# Pfad zur SQLite-Datenbankdatei
DATABASE_URL = "sqlite:///./app.db"

# SQLAlchemy Basis für Deklaration von Modellen
Base = declarative_base()

# Definition der User-Tabelle
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False) 
    email = Column(String, unique=True, index=True, nullable=False) 
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True) 
    is_verified = Column(Boolean, default=False) 
    registration_date = Column(DateTime, default=datetime.utcnow) 

    # Beziehungen zu den neuen Tabellen - mit String-Referenzen für Forward Declaration
    smtp_settings = relationship("SmtpSettings", backref="user", uselist=False, cascade="all, delete-orphan")
    password_reset_tokens = relationship("PasswordResetToken", backref="user", cascade="all, delete-orphan")
    email_verification_tokens = relationship("EmailVerificationToken", backref="user", cascade="all, delete-orphan")
    process_log_entries = relationship("ProcessLogEntry", backref="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}')>"

# Definition der SMTP-Einstellungen-Tabelle
class SmtpSettings(Base):
    __tablename__ = 'smtp_settings'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    encrypted_host = Column(Text, nullable=False)
    encrypted_user = Column(Text, nullable=False)
    encrypted_pass = Column(Text, nullable=False)
    encrypted_port = Column(Text, nullable=False)
    encrypted_secure = Column(Text, nullable=False)

    __table_args__ = (UniqueConstraint('user_id', name='uq_user_id'),)

    def __repr__(self):
        return f"<SmtpSettings(id={self.id}, user_id={self.user_id})>"

# Definition der PasswordResetTokens-Tabelle
class PasswordResetToken(Base):
    __tablename__ = 'password_reset_tokens'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False) 

    def __repr__(self):
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id}, expires_at='{self.expires_at}')>"

# Definition der EmailVerificationTokens-Tabelle
class EmailVerificationToken(Base):
    __tablename__ = 'email_verification_tokens'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False) 

    def __repr__(self):
        return f"<EmailVerificationToken(id={self.id}, user_id={self.user_id}, expires_at='{self.expires_at}')>"

# Definition der ProcessLogEntry-Tabelle für die Historie der Serienmail-Vorgänge
class ProcessLogEntry(Base):
    __tablename__ = 'process_log_entries'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    excel_file_original_name = Column(String, nullable=False)
    word_template_original_name = Column(String, nullable=False)
    filter_column = Column(String, nullable=True)
    filter_value = Column(String, nullable=True)
    email_subject_template = Column(String, nullable=False)
    email_body_template = Column(Text, nullable=False)
    from_name = Column(String, nullable=True)
    total_recipients = Column(Integer, nullable=False)
    sent_emails_count = Column(Integer, nullable=False)
    status = Column(String, nullable=False) # 'completed', 'failed', 'partial_success'
    
    # Beziehung zu GeneratedFile
    generated_files = relationship("GeneratedFile", backref="process_log_entry", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ProcessLogEntry(id={self.id}, user_id={self.user_id}, timestamp='{self.timestamp}', status='{self.status}')>"

# Definition der GeneratedFile-Tabelle für Details zu jeder generierten Datei
class GeneratedFile(Base):
    __tablename__ = 'generated_files'
    id = Column(Integer, primary_key=True, index=True)
    process_id = Column(Integer, ForeignKey('process_log_entries.id'), nullable=False)
    recipient_email = Column(String, nullable=False)
    recipient_name = Column(String, nullable=False)
    pdf_filename = Column(String, nullable=False)
    pdf_storage_path = Column(String, nullable=False)
    email_sent_status = Column(String, nullable=False) # 'success', 'failed'
    email_sent_message = Column(Text, nullable=True)
    sent_timestamp = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<GeneratedFile(id={self.id}, process_id={self.process_id}, recipient_email='{self.recipient_email}', status='{self.email_sent_status}')>"


# Datenbank-Engine und Session-Erstellung
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Funktion zum Erstellen der Datenbanktabellen
def create_db_and_tables():
    Base.metadata.create_all(bind=engine)

# Beispiel-Anwendung (nur zum Testen oder für Initialisierung)
if __name__ == "__main__":
    from security import encrypt_data
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # WICHTIG: Wenn Sie die DB-Struktur geändert haben und bestehende Daten löschen möchten,
    # können Sie die app.db-Datei manuell löschen, BEVOR Sie create_db_and_tables() aufrufen.
    if os.path.exists("./app.db"):
        print("Bestehende app.db gefunden. Für eine saubere Neuinitialisierung mit neuen Tabellen bitte manuell löschen.")
        # os.remove("./app.db") # Uncomment diese Zeile, um die DB zu löschen!
        # print("app.db gelöscht.")

    create_db_and_tables()
    print("Datenbank und Tabellen erstellt (app.db).")

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == "test@example.com").first():
            hashed_password = pwd_context.hash("testpass")
            test_user = User(username="testuser", email="test@example.com", password_hash=hashed_password, is_verified=True, is_active=True)
            db.add(test_user)
            db.commit()
            db.refresh(test_user) 
            print(f"Benutzer 'testuser' mit ID {test_user.id} und E-Mail {test_user.email} erstellt.")

            test_smtp_host = "smtp.example.com"
            test_smtp_user = "test@example.com"
            test_smtp_pass = "smtp_password"
            test_smtp_port = "587"
            test_smtp_secure = "tls"

            ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
            if not ENCRYPTION_KEY:
                print("FEHLER: ENCRYPTION_KEY nicht in .env gefunden. Kann SMTP-Einstellungen nicht verschlüsseln.")
            else:
                encrypted_host = encrypt_data(test_smtp_host, ENCRYPTION_KEY)
                encrypted_user = encrypt_data(test_smtp_user, ENCRYPTION_KEY)
                encrypted_pass = encrypt_data(test_smtp_pass, ENCRYPTION_KEY)
                encrypted_port = encrypt_data(test_smtp_port, ENCRYPTION_KEY)
                encrypted_secure = encrypt_data(test_smtp_secure, ENCRYPTION_KEY)

                test_smtp_settings = SmtpSettings(
                    user_id=test_user.id,
                    encrypted_host=encrypted_host,
                    encrypted_user=encrypted_user,
                    encrypted_pass=encrypted_pass,
                    encrypted_port=encrypted_port,
                    encrypted_secure=encrypted_secure
                )
                db.add(test_smtp_settings)
                db.commit()
                db.refresh(test_smtp_settings)
                print(f"Beispiel-SMTP-Einstellungen für Benutzer {test_user.username} erstellt.")
        else:
            print("Benutzer 'test@example.com' existiert bereits.")

    except IntegrityError:
        db.rollback()
        print("Benutzer 'testuser' oder SMTP-Einstellungen existieren bereits (IntegrityError).")
    except Exception as e:
        db.rollback()
        print(f"Fehler bei der Datenbank-Initialisierung: {e}")
    finally:
        db.close()