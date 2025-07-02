from database import SessionLocal, User
db = SessionLocal()

# Ihren neuen Benutzer aktivieren
user = db.query(User).filter(User.email == "shuettemann@gmail.com").first()
if user:
    user.is_verified = True
    db.commit()
    print("Benutzer aktiviert!")
else:
    print("Benutzer nicht gefunden")
db.close()