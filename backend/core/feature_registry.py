from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any


class FeatureStatus(str, Enum):
    ACTIVE = "active"
    ADMIN_ONLY = "admin_only"
    NEEDS_SETUP = "needs_setup"
    DISABLED = "disabled"
    HIDDEN = "hidden"


@dataclass(frozen=True)
class FeatureDefinition:
    key: str
    name: str
    status: FeatureStatus
    requires_env: tuple[str, ...] = ()
    user_visible: bool = True
    admin_visible: bool = True
    reason: str = ""

    def to_dict(self, env_status: dict[str, bool] | None = None) -> dict[str, Any]:
        missing = []
        if env_status is not None:
            missing = [key for key in self.requires_env if not env_status.get(key, False)]
        data = asdict(self)
        data["status"] = self.status.value
        data["requires_env"] = list(self.requires_env)
        data["missing_env"] = missing
        data["ready"] = self.status == FeatureStatus.ACTIVE and not missing
        if missing and self.status == FeatureStatus.ACTIVE:
            data["effective_status"] = FeatureStatus.NEEDS_SETUP.value
        else:
            data["effective_status"] = self.status.value
        return data


FEATURES: dict[str, FeatureDefinition] = {
    "home": FeatureDefinition("home", "Home deals", FeatureStatus.ACTIVE),
    "products": FeatureDefinition("products", "Products", FeatureStatus.ACTIVE),
    "search": FeatureDefinition("search", "Search", FeatureStatus.ACTIVE),
    "ai_search": FeatureDefinition("ai_search", "AI search", FeatureStatus.ACTIVE, requires_env=("GROQ_API_KEY",)),
    "ai_brain": FeatureDefinition("ai_brain", "AI Deal Brain", FeatureStatus.ACTIVE, requires_env=("GROQ_API_KEY",)),
    "scan": FeatureDefinition("scan", "Scan", FeatureStatus.ACTIVE, requires_env=("GROQ_API_KEY",)),
    "visual_search": FeatureDefinition("visual_search", "Visual search", FeatureStatus.ACTIVE, requires_env=("GROQ_API_KEY",)),
    "voice_search": FeatureDefinition("voice_search", "Voice search", FeatureStatus.ACTIVE),
    "reels": FeatureDefinition("reels", "Deal Reels", FeatureStatus.ACTIVE, requires_env=("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")),
    "messages": FeatureDefinition("messages", "Messages", FeatureStatus.ACTIVE),
    "profile": FeatureDefinition("profile", "Profiles", FeatureStatus.ACTIVE),
    "marketplace": FeatureDefinition("marketplace", "Marketplace", FeatureStatus.ACTIVE),
    "alerts": FeatureDefinition("alerts", "Alerts", FeatureStatus.ACTIVE),
    "geo_alerts": FeatureDefinition("geo_alerts", "Geo Alerts", FeatureStatus.ACTIVE),
    "admin": FeatureDefinition("admin", "Admin", FeatureStatus.ADMIN_ONLY, user_visible=False),
    "connectors": FeatureDefinition("connectors", "Store Connectors", FeatureStatus.ADMIN_ONLY, user_visible=False),
    "amazon_connector": FeatureDefinition("amazon_connector", "Amazon Connector", FeatureStatus.NEEDS_SETUP, requires_env=("AMAZON_ACCESS_KEY", "AMAZON_SECRET_KEY", "AMAZON_PARTNER_TAG"), user_visible=False),
    "aliexpress_connector": FeatureDefinition("aliexpress_connector", "AliExpress Connector", FeatureStatus.NEEDS_SETUP, requires_env=("ALIEXPRESS_APP_KEY", "ALIEXPRESS_APP_SECRET"), user_visible=False),
    "cashback": FeatureDefinition("cashback", "Cashback", FeatureStatus.NEEDS_SETUP, user_visible=False, reason="Requires verified affiliate conversion tracking and payout rules."),
    "coupons_p2p": FeatureDefinition("coupons_p2p", "P2P Coupons", FeatureStatus.ADMIN_ONLY, user_visible=False, reason="Requires moderation and fraud controls before public launch."),
    "mystery_box": FeatureDefinition("mystery_box", "Mystery Box", FeatureStatus.ADMIN_ONLY, user_visible=False, reason="Requires real reward pool and abuse protection before public launch."),
}


def env_status(keys: list[str] | tuple[str, ...]) -> dict[str, bool]:
    import os
    return {key: bool(os.getenv(key, "").strip()) for key in keys}


def all_required_env_keys() -> list[str]:
    keys: set[str] = set()
    for feature in FEATURES.values():
        keys.update(feature.requires_env)
    keys.update({"OFERTIX_ADMIN_EMAILS", "FIREBASE_PROJECT_ID"})
    return sorted(keys)


def feature_payload(admin: bool = False) -> dict[str, Any]:
    status = env_status(all_required_env_keys())
    data: dict[str, Any] = {}
    for key, feature in FEATURES.items():
        if admin:
            if not feature.admin_visible:
                continue
        else:
            if not feature.user_visible:
                continue
        data[key] = feature.to_dict(status)
    return data


def is_user_visible(key: str) -> bool:
    feature = FEATURES.get(key)
    if not feature:
        return False
    if feature.status != FeatureStatus.ACTIVE or not feature.user_visible:
        return False
    return all(bool(__import__('os').getenv(env, '').strip()) for env in feature.requires_env)
