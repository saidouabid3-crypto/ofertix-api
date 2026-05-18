import os
import json
import firebase_admin

from dotenv import load_dotenv
from firebase_admin import credentials, firestore

load_dotenv()

firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
firebase_key_path = os.getenv("FIREBASE_KEY_PATH", "firebase_key.json")

if not firebase_admin._apps:
    if firebase_credentials:
        cred_dict = json.loads(firebase_credentials)
        cred = credentials.Certificate(cred_dict)
    else:
        cred = credentials.Certificate(firebase_key_path)

    firebase_admin.initialize_app(cred)

db = firestore.client()