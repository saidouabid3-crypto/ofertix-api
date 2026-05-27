from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import require_admin
from schemas.setup_schema import SetupStatusResponse
from services.setup_service import setup_service

router = APIRouter(prefix='/setup', tags=['Setup'])


@router.get('/public', response_model=SetupStatusResponse)
def public_setup_status():
    # Public status only exposes user-visible feature readiness.
    return setup_service.status(admin=False)


@router.get('/admin', response_model=SetupStatusResponse)
def admin_setup_status(current_user: dict = Depends(require_admin)):
    return setup_service.status(admin=True)
