from fastapi import APIRouter, Depends

from core.auth import require_admin
from schemas.admin_schema import AdminDashboardResponse
from services.admin_service import admin_service

router = APIRouter(prefix='/admin', tags=['Admin'])


@router.get('/dashboard', response_model=AdminDashboardResponse)
def dashboard(current_user: dict = Depends(require_admin)):
    return admin_service.dashboard()
