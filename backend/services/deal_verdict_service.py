from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_BLOCKED_STATUSES = {
    "blocked",
    "expired",
    "hidden",
    "quarantined",
    "rejected",
}
_VALID_CURRENCIES = {"AED", "DZD", "EUR", "GBP", "JPY", "MAD", "USD"}
_APPROXIMATE_WORDS = {
    "approx",
    "approximate",
    "estimated",
    "estimado",
    "aproximado",
    "environ",
}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return default
    try:
        raw = (
            str(value)
            .replace("€", "")
            .replace("$", "")
            .replace("£", "")
            .replace("%", "")
            .strip()
        )
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", ".")
        return float(raw)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "active"}
    return default


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _flags(product: dict[str, Any]) -> set[str]:
    raw = product.get("qualityFlags") or []
    if isinstance(raw, str):
        raw = raw.replace("|", ",").replace(";", ",").split(",")
    return {str(flag).strip().lower() for flag in raw if str(flag).strip()}


def _valid_link(product: dict[str, Any]) -> bool:
    health = product.get("linkHealth")
    if isinstance(health, dict) and health.get("isValidHttpUrl") is not None:
        return _bool(health.get("isValidHttpUrl"))
    link = str(
        product.get("affiliateUrl")
        or product.get("productUrl")
        or product.get("url")
        or ""
    ).strip()
    return link.startswith(("http://", "https://")) and len(link) > 10


def _image_count(product: dict[str, Any]) -> int:
    media = product.get("mediaQuality")
    if isinstance(media, dict):
        count = int(_number(media.get("validImageCount"), -1))
        if count >= 0:
            return count
    images = product.get("images") or []
    if isinstance(images, list):
        return len({
            str(image).strip()
            for image in images
            if str(image).strip().startswith(("http://", "https://"))
        })
    return 1 if str(product.get("image") or product.get("mainImage") or "").strip() else 0


def _days_old(product: dict[str, Any]) -> int | None:
    raw = (
        product.get("priceLastCheckedAt")
        or product.get("lastUpdatedFromFeed")
        or product.get("updatedAt")
    )
    if raw is None:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    else:
        text = str(raw).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def _add_reason(
    reasons: list[dict[str, str]],
    reason_type: str,
    code: str,
    message: str,
) -> None:
    if any(reason["code"] == code for reason in reasons):
        return
    reasons.append({"type": reason_type, "code": code, "message": message})


def _risk_level(score: int) -> str:
    if score >= 85:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _labels(verdict: str, risk_level: str) -> tuple[str, str]:
    verdict_labels = {
        "buy_now": "Buy now",
        "wait": "Wait",
        "check_store": "Check store",
        "avoid": "Avoid",
    }
    risk_labels = {
        "low": "Low discount risk",
        "medium": "Medium discount risk",
        "high": "High discount risk",
        "critical": "Critical discount risk",
    }
    return verdict_labels[verdict], risk_labels[risk_level]


def analyze_deal_verdict(
    product: dict[str, Any],
    *,
    market: str = "es",
) -> dict[str, Any]:
    """
    Analyze existing catalog signals without external calls or inferred history.

    Confidence measures evidence completeness. Discount risk measures uncertainty
    or inconsistency in the advertised discount; it never declares fraud.
    """
    del market  # Reserved for future market-specific thresholds.

    reasons: list[dict[str, str]] = []
    warnings: list[str] = []
    action_hints: list[str] = []
    flags = _flags(product)

    new_price = _number(product.get("newPrice") or product.get("price"))
    old_price = _number(product.get("oldPrice") or product.get("originalPrice"))
    discount = max(0.0, _number(product.get("discount")))
    quality = max(0.0, min(100.0, _number(product.get("qualityScore"), 50)))
    category_confidence = max(
        0.0, min(1.0, _number(product.get("categoryConfidence")))
    )
    trust = _text(product.get("trustStatus"))
    status = _text(product.get("status") or "active")
    price_confidence = _text(product.get("priceConfidence"))
    price_accuracy = _text(product.get("priceAccuracy") or "estimated")
    price_source = _text(product.get("priceSource") or product.get("source"))
    price_note = _text(product.get("priceNote"))
    final_price_in_store = _bool(product.get("finalPriceInStore"), True)
    has_valid_link = _valid_link(product) and not (
        flags & {"missing_link", "invalid_link"}
    )
    image_count = _image_count(product)
    duplicate_status = _text(product.get("duplicateStatus"))
    stock = _text(product.get("stockAvailability"))
    shipping = _text(product.get("shippingConfidence"))
    currency = str(product.get("currency") or "").strip().upper()
    visible = product.get("visibleToUsers") is not False
    category = _text(
        product.get("normalizedCategory")
        or product.get("categoryGroup")
        or product.get("category")
    )
    price_age_days = _days_old(product)

    confidence = 50.0
    deal_score = 50.0
    discount_risk = 10.0
    critical_issue = False

    if trust in {"trusted", "ok"}:
        confidence += 15
        deal_score += 15
        _add_reason(
            reasons, "positive", "trusted_product",
            "Product quality signals look good.",
        )
    else:
        confidence -= 10
        deal_score -= 10
        _add_reason(
            reasons, "warning", "limited_trust",
            "Product trust signals are limited.",
        )

    if quality >= 80:
        confidence += 10
        deal_score += 10
        _add_reason(
            reasons, "positive", "high_quality",
            "Catalog quality signals are strong.",
        )
    elif quality < 50:
        confidence -= 10
        deal_score -= 10
        _add_reason(
            reasons, "warning", "low_quality",
            "Some catalog information may be incomplete.",
        )

    if has_valid_link:
        confidence += 8
        deal_score += 8
    else:
        confidence -= 30
        deal_score -= 30
        discount_risk += 15
        critical_issue = True
        _add_reason(
            reasons, "negative", "missing_link",
            "A valid store link is not available.",
        )

    if new_price <= 0 or "missing_price" in flags:
        confidence -= 25
        deal_score -= 25
        discount_risk += 35
        critical_issue = True
        _add_reason(
            reasons, "negative", "missing_price",
            "A usable current price is missing.",
        )

    if currency not in _VALID_CURRENCIES or "missing_currency" in flags:
        confidence -= 18
        deal_score -= 18
        discount_risk += 12
        _add_reason(
            reasons, "warning", "missing_currency",
            "The price currency needs confirmation.",
        )

    if price_confidence in {"confirmed", "high", "verified"}:
        confidence += 12
        discount_risk -= 10
        _add_reason(
            reasons, "positive", "confirmed_price",
            "The available price signal has good confidence.",
        )
    elif price_confidence in {"missing", "needs_review", "low"}:
        confidence -= 18
        discount_risk += 18
        _add_reason(
            reasons, "warning", "weak_price_confidence",
            "The available price signal has low confidence.",
        )

    estimated_price = (
        price_accuracy in {"estimated", "approximate", "feed"}
        or price_confidence in {"approximate", "estimated"}
        or any(word in price_note for word in _APPROXIMATE_WORDS)
    )
    if estimated_price:
        confidence -= 12
        deal_score -= 12
        discount_risk += 12
        _add_reason(
            reasons, "warning", "estimated_price",
            "Price is estimated from an affiliate feed.",
        )

    if final_price_in_store:
        confidence -= 10
        deal_score -= 10
        discount_risk += 8
        warnings.append("Final price may change in store.")
        _add_reason(
            reasons, "warning", "final_price_in_store",
            "The final price must be confirmed in store.",
        )
        if "impact" in price_source:
            discount_risk += 8

    if 20 <= discount <= 70:
        deal_score += 6
        discount_risk -= 6
        _add_reason(
            reasons, "positive", "reasonable_discount",
            "The advertised discount is within a common range.",
        )
    elif discount >= 85:
        discount_risk += 18
        _add_reason(
            reasons, "warning", "very_high_discount",
            "The advertised discount is unusually high.",
        )
        if estimated_price:
            deal_score -= 25
            discount_risk += 25
            warnings.append("The advertised discount may be inflated.")

    if old_price > 0 and new_price > 0:
        implied_discount = max(0.0, (old_price - new_price) / old_price * 100)
        if old_price <= new_price and discount >= 20:
            deal_score -= 22
            discount_risk += 35
            _add_reason(
                reasons, "negative", "discount_price_mismatch",
                "The old and current prices do not support the advertised discount.",
            )
        elif abs(implied_discount - discount) >= 20 and discount >= 20:
            deal_score -= 12
            discount_risk += 22
            _add_reason(
                reasons, "warning", "discount_price_mismatch",
                "The advertised discount does not closely match the listed prices.",
            )
        if old_price / new_price >= 8:
            deal_score -= 15
            discount_risk += 25
            _add_reason(
                reasons, "warning", "unusual_price_ratio",
                "The old-to-current price ratio is unusually large.",
            )

    if "suspicious_price" in flags:
        confidence -= 20
        deal_score -= 20
        discount_risk += 30
        _add_reason(
            reasons, "negative", "suspicious_price",
            "The current price needs additional verification.",
        )

    duplicate_candidate = (
        "duplicate_candidate" in flags
        or duplicate_status in {
            "candidate", "duplicate_candidate", "possible_duplicate"
        }
    )
    if duplicate_candidate:
        confidence -= 18
        deal_score -= 18
        discount_risk += 10
        _add_reason(
            reasons, "warning", "duplicate_candidate",
            "This listing may duplicate another catalog offer.",
        )

    if image_count <= 1 or "single_image_only" in flags:
        confidence -= 15
        deal_score -= 5
        _add_reason(
            reasons, "warning", "single_image_only",
            "Only limited product imagery is available.",
        )

    if category in {"", "general", "other", "unknown"} or "unknown_category" in flags:
        confidence -= 15
        deal_score -= 10
        discount_risk += 5
        _add_reason(
            reasons, "warning", "unknown_category",
            "The product category has low confidence.",
        )
    elif category_confidence >= 0.75:
        confidence += 8
        deal_score += 8

    if stock in {"instock", "in_stock", "available"}:
        confidence += 8
        deal_score += 8
    elif stock in {"outofstock", "out_of_stock", "unavailable"}:
        deal_score -= 20
        _add_reason(
            reasons, "warning", "stock_unavailable",
            "Current stock availability is uncertain or unavailable.",
        )

    if shipping in {"medium", "high", "confirmed"}:
        confidence += 4
        deal_score += 4
    elif shipping in {"", "low", "missing", "unknown"}:
        confidence -= 8
        deal_score -= 8
        _add_reason(
            reasons, "warning", "shipping_uncertain",
            "Shipping cost or availability should be confirmed.",
        )

    if price_age_days is None:
        confidence -= 10
        discount_risk += 8
        _add_reason(
            reasons, "warning", "price_check_missing",
            "The last price check time is unavailable.",
        )
    elif price_age_days > 7:
        confidence -= 10
        discount_risk += 10
        _add_reason(
            reasons, "warning", "price_check_old",
            "The available price check may be out of date.",
        )

    # This service intentionally has no verified price-history source.
    confidence -= 5
    _add_reason(
        reasons, "warning", "price_history_unavailable",
        "No verified price history is available for this verdict.",
    )

    if _bool(product.get("isHot")):
        deal_score += 5
    if _bool(product.get("featured")):
        deal_score += 4

    blocked = (
        status in _BLOCKED_STATUSES
        or trust in _BLOCKED_STATUSES
        or _bool(product.get("isExpired"))
        or not visible
    )
    if blocked:
        confidence -= 35
        deal_score -= 35
        discount_risk += 20
        critical_issue = True
        _add_reason(
            reasons, "negative", "product_unavailable",
            "This product is not currently eligible for purchase guidance.",
        )

    confidence_int = round(max(0.0, min(100.0, confidence)))
    deal_score_int = round(max(0.0, min(100.0, deal_score)))
    discount_risk_int = round(max(0.0, min(100.0, discount_risk)))
    risk_level = _risk_level(discount_risk_int)

    if critical_issue:
        verdict = "avoid"
    elif risk_level in {"high", "critical"}:
        verdict = "wait" if deal_score_int >= 40 else "avoid"
    elif deal_score_int >= 75:
        verdict = "buy_now"
    elif deal_score_int >= 55:
        verdict = "check_store"
    elif deal_score_int >= 40:
        verdict = "wait"
    else:
        verdict = "avoid"

    if final_price_in_store and estimated_price and verdict == "buy_now":
        verdict = "check_store"

    summaries = {
        "buy_now": (
            "This looks like a good deal based on available signals. "
            "Confirm the final price and availability in store."
        ),
        "check_store": (
            "Good signals are available, but the final price, shipping, "
            "and availability should be confirmed in store."
        ),
        "wait": (
            "Price or discount confidence is limited. Wait if you are not "
            "in a hurry, or verify the offer in store."
        ),
        "avoid": (
            "Key purchase information is missing or risky. Avoid this offer "
            "until the details can be verified."
        ),
    }

    if verdict in {"buy_now", "check_store"}:
        action_hints.append(
            "Open the store and confirm final price, shipping, and availability."
        )
    elif verdict == "wait":
        action_hints.append(
            "Compare another offer or wait for clearer price information."
        )
    else:
        action_hints.append(
            "Choose another offer with a valid price, link, and stronger trust signals."
        )

    label, discount_risk_label = _labels(verdict, risk_level)
    return {
        "verdict": verdict,
        "label": label,
        "confidence": confidence_int,
        "riskLevel": risk_level,
        "discountRiskScore": discount_risk_int,
        "discountRiskLabel": discount_risk_label,
        "summary": summaries[verdict],
        "reasons": reasons,
        "warnings": list(dict.fromkeys(warnings)),
        "actionHints": action_hints,
        "signals": {
            "priceConfidence": price_confidence or "unknown",
            "priceAccuracy": price_accuracy or "unknown",
            "priceSource": price_source or "unknown",
            "trustStatus": trust or "unknown",
            "qualityScore": round(quality),
            "hasValidLink": has_valid_link,
            "finalPriceInStore": final_price_in_store,
            "discount": round(discount),
            "priceHistoryAvailable": False,
            "priceAgeDays": price_age_days,
            "imageCount": image_count,
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
