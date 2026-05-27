from typing import Any, Dict

from repositories.admin_repository import AdminRepository


class AdminService:
    def __init__(self) -> None:
        self.repo = AdminRepository()

    def dashboard(self) -> Dict[str, Any]:
        return self.repo.dashboard()


admin_service = AdminService()
