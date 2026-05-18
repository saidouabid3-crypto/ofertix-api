import os
import firebase_admin

from dotenv import load_dotenv
from firebase_admin import credentials, firestore

load_dotenv()

FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "firebase_key.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()