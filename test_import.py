try:
    from database import ProcessLogEntry, GeneratedFile
    print("Import erfolgreich!")
    print(f"ProcessLogEntry: {ProcessLogEntry}")
    print(f"GeneratedFile: {GeneratedFile}")
except Exception as e:
    print(f"Import-Fehler: {e}")
    import traceback
    traceback.print_exc()