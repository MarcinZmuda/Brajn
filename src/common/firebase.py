"""
Firebase/Firestore initialization — shared across all modules.
"""
import json
import firebase_admin
from firebase_admin import credentials, firestore
from src.common.config import GOOGLE_APPLICATION_CREDENTIALS, FIREBASE_CREDS_JSON

_db = None

def get_db():
    """Lazy-init Firestore client. Returns firestore.Client or None."""
    global _db
    if _db is not None:
        return _db

    if firebase_admin._apps:
        _db = firestore.client()
        return _db

    try:
        if FIREBASE_CREDS_JSON:
            creds_dict = json.loads(FIREBASE_CREDS_JSON)
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred)
        elif GOOGLE_APPLICATION_CREDENTIALS:
            try:
                creds_dict = json.loads(GOOGLE_APPLICATION_CREDENTIALS)
                cred = credentials.Certificate(creds_dict)
                firebase_admin.initialize_app(cred)
            except json.JSONDecodeError:
                cred = credentials.Certificate(GOOGLE_APPLICATION_CREDENTIALS)
                firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()

        _db = firestore.client()
        print("[FIREBASE] Firestore initialized")
    except Exception as e:
        print(f"[FIREBASE] Init skipped: {e}")
        _db = None

    return _db


PROJECTS_COLLECTION = "seo_projects"


def save_project(project_id: str, data: dict):
    db = get_db()
    if not db:
        return
    try:
        db.collection(PROJECTS_COLLECTION).document(project_id).set(data, merge=True)
    except Exception as e:
        print(f"[FIREBASE] Error saving project {project_id}: {e}")


def load_project(project_id: str) -> dict | None:
    db = get_db()
    if not db:
        return None
    try:
        doc = db.collection(PROJECTS_COLLECTION).document(project_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print(f"[FIREBASE] Error loading project {project_id}: {e}")
        return None
