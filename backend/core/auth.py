from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth

# Import initializes firebase_admin through existing project code.
from core.firebase import db  # noqa: F401


def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail='Missing Authorization header')

    parts = authorization.split(' ', 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise HTTPException(status_code=401, detail='Invalid Authorization header')

    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail='Empty Firebase token')

    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail='Invalid or expired Firebase token')

    uid = decoded.get('uid')
    if not uid:
        raise HTTPException(status_code=401, detail='Invalid Firebase user')

    return {
        'uid': uid,
        'email': decoded.get('email') or '',
        'name': decoded.get('name') or '',
        'picture': decoded.get('picture') or '',
    }


def optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization:
        return None
    try:
        return require_user(authorization)
    except HTTPException:
        return None



def _is_admin_from_firestore(uid: str) -> bool:
    try:
        doc = db.collection('users').document(uid).get()
        if not doc.exists:
            return False
        data = doc.to_dict() or {}
        role = str(data.get('role') or data.get('userRole') or '').lower().strip()
        return bool(
            data.get('isAdmin') is True
            or data.get('admin') is True
            or role in {'admin', 'owner', 'super_admin'}
        )
    except Exception:
        return False


def _is_admin_from_env(email: str) -> bool:
    import os

    admins = os.getenv('OFERTIX_ADMIN_EMAILS', '')
    allowed = {item.strip().lower() for item in admins.split(',') if item.strip()}
    return bool(email and email.lower().strip() in allowed)


def require_admin(current_user: dict = None, authorization: str | None = Header(default=None)) -> dict:
    user = current_user or require_user(authorization)
    uid = user.get('uid') or ''
    email = user.get('email') or ''

    if _is_admin_from_env(email) or _is_admin_from_firestore(uid):
        return user

    raise HTTPException(status_code=403, detail='Admin access required')
