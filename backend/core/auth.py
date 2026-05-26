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
