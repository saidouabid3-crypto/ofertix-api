from __future__ import annotations

import os
from typing import Any

from core.feature_registry import all_required_env_keys, feature_payload


class SetupService:
    def status(self, admin: bool = False) -> dict[str, Any]:
        keys = all_required_env_keys()
        configured = [key for key in keys if os.getenv(key, '').strip()]
        missing = [key for key in keys if key not in configured]
        warnings: list[str] = []
        if 'OFERTIX_ADMIN_EMAILS' in missing:
            warnings.append('Admin emails are not configured. Render env OFERTIX_ADMIN_EMAILS is required for secure admin access.')
        ai_keys = {'GROQ_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY'}
        if ai_keys <= set(missing):
            warnings.append('No AI provider key is configured. AI features should show setup-needed instead of crashing.')
        if any(key in missing for key in ['CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET']):
            warnings.append('Cloudinary is not fully configured. Reels feed can play existing URLs, but uploads need setup.')
        return {
            'ok': True,
            'missingEnv': missing,
            'configuredEnv': configured,
            'features': feature_payload(admin=admin),
            'warnings': warnings,
        }


setup_service = SetupService()
