"""Localized error payloads.

Builds JSON error responses whose ``safeMessage`` is written in the active
request locale, so the Flutter client can surface a friendly message in the
user's language even when the backend fails (LLM timeout, serialization error,
upstream outage). The machine-readable ``code`` and ``detail`` stay stable for
logging and client-side branching.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from core.locale_context import LocaleState, get_locale

# Friendly, user-facing messages per supported language. Keyed by an internal
# message id; unknown languages fall back to English.
_MESSAGES: dict[str, dict[str, str]] = {
    "ai_unavailable": {
        "en": "The AI service is busy right now. Please try again in a moment.",
        "es": "El servicio de IA está ocupado ahora mismo. Inténtalo de nuevo en un momento.",
        "fr": "Le service IA est occupé pour le moment. Réessayez dans un instant.",
        "ar": "خدمة الذكاء الاصطناعي مشغولة حاليًا. حاول مرة أخرى بعد قليل.",
        "de": "Der KI-Dienst ist gerade ausgelastet. Bitte versuche es gleich erneut.",
        "it": "Il servizio AI è occupato in questo momento. Riprova tra poco.",
        "pt": "O serviço de IA está ocupado agora. Tente novamente em instantes.",
        "nl": "De AI-service is momenteel bezet. Probeer het zo opnieuw.",
        "tr": "Yapay zekâ servisi şu anda meşgul. Lütfen birazdan tekrar deneyin.",
    },
    "ai_timeout": {
        "en": "The analysis took too long. Please try again.",
        "es": "El análisis tardó demasiado. Inténtalo de nuevo.",
        "fr": "L’analyse a pris trop de temps. Veuillez réessayer.",
        "ar": "استغرق التحليل وقتًا طويلًا. حاول مرة أخرى.",
        "de": "Die Analyse hat zu lange gedauert. Bitte versuche es erneut.",
        "it": "L’analisi ha richiesto troppo tempo. Riprova.",
        "pt": "A análise demorou demais. Tente novamente.",
        "nl": "De analyse duurde te lang. Probeer het opnieuw.",
        "tr": "Analiz çok uzun sürdü. Lütfen tekrar deneyin.",
    },
    "bad_data": {
        "en": "We couldn't read this product. Please check the details and try again.",
        "es": "No pudimos leer este producto. Revisa los datos e inténtalo de nuevo.",
        "fr": "Nous n’avons pas pu lire ce produit. Vérifiez les détails et réessayez.",
        "ar": "لم نتمكن من قراءة هذا المنتج. تحقق من التفاصيل وحاول مجددًا.",
        "de": "Dieses Produkt konnte nicht gelesen werden. Prüfe die Angaben und versuche es erneut.",
        "it": "Non è stato possibile leggere questo prodotto. Controlla i dati e riprova.",
        "pt": "Não foi possível ler este produto. Verifique os dados e tente novamente.",
        "nl": "We konden dit product niet lezen. Controleer de gegevens en probeer opnieuw.",
        "tr": "Bu ürünü okuyamadık. Lütfen bilgileri kontrol edip tekrar deneyin.",
    },
    "scan_failed": {
        "en": "We couldn't find this scanned product. Try searching by name.",
        "es": "No encontramos este producto escaneado. Prueba a buscarlo por nombre.",
        "fr": "Produit scanné introuvable. Essayez de chercher par nom.",
        "ar": "لم نجد هذا المنتج الممسوح. جرّب البحث بالاسم.",
        "de": "Gescanntes Produkt nicht gefunden. Suche es per Name.",
        "it": "Prodotto scansionato non trovato. Prova a cercarlo per nome.",
        "pt": "Produto digitalizado não encontrado. Tente buscar pelo nome.",
        "nl": "Gescand product niet gevonden. Zoek op naam.",
        "tr": "Taranan ürün bulunamadı. Adıyla aramayı deneyin.",
    },
}


def localized_message(message_id: str, locale: LocaleState | None = None) -> str:
    state = locale or get_locale()
    table = _MESSAGES.get(message_id, _MESSAGES["ai_unavailable"])
    return table.get(state.language, table["en"])


def localized_error_response(
    *,
    status_code: int,
    code: str,
    message_id: str,
    detail: str | None = None,
    locale: LocaleState | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> JSONResponse:
    state = locale or get_locale()
    safe_message = localized_message(message_id, state)
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail or code,
            "code": code,
            "safeMessage": safe_message,
            "meta": {
                "language": state.language,
                "country": state.effective_country,
                **(extra_meta or {}),
            },
        },
    )
