from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from core.locale_context import get_locale
from repositories.ai_brain_repository import ai_brain_repository
from services.ai_service import ai_service
from services.deal_score_service import DealScoreService
from services.fake_discount_service import FakeDiscountService


_REASONS: dict[str, dict[str, str]] = {
    "price_not_lower": {
        "en": "The old price does not beat the current price.",
        "es": "El precio antiguo no mejora el precio actual.",
        "fr": "L'ancien prix n'est pas meilleur que le prix actuel.",
        "ar": "السعر القديم لا يتفوق على السعر الحالي.",
        "de": "Der alte Preis ist nicht besser als der aktuelle.",
        "it": "Il vecchio prezzo non supera il prezzo attuale.",
        "pt": "O preço antigo não supera o preço atual.",
        "nl": "De oude prijs is niet beter dan de huidige prijs.",
        "tr": "Eski fiyat mevcut fiyatı geçmiyor.",
    },
    "strong_discount": {
        "en": "Strong discount of approximately {discount}%.",
        "es": "Descuento fuerte aproximado de {discount}%.",
        "fr": "Remise importante d'environ {discount}%.",
        "ar": "خصم قوي بنسبة {discount}% تقريبًا.",
        "de": "Starker Rabatt von ca. {discount}%.",
        "it": "Forte sconto di circa il {discount}%.",
        "pt": "Desconto forte de aproximadamente {discount}%.",
        "nl": "Sterke korting van ongeveer {discount}%.",
        "tr": "Yaklaşık %{discount} güçlü indirim.",
    },
    "fair_discount": {
        "en": "Reasonable discount of approximately {discount}%.",
        "es": "Descuento interesante aproximado de {discount}%.",
        "fr": "Remise intéressante d'environ {discount}%.",
        "ar": "خصم معقول بنسبة {discount}% تقريبًا.",
        "de": "Angemessener Rabatt von ca. {discount}%.",
        "it": "Sconto ragionevole di circa il {discount}%.",
        "pt": "Desconto razoável de aproximadamente {discount}%.",
        "nl": "Redelijke korting van ongeveer {discount}%.",
        "tr": "Yaklaşık %{discount} makul indirim.",
    },
    "small_discount": {
        "en": "There is a discount, but it does not seem aggressive enough.",
        "es": "La rebaja existe, pero no parece agresiva.",
        "fr": "Il y a une remise, mais elle ne semble pas agressive.",
        "ar": "يوجد خصم، لكنه ليس كافياً.",
        "de": "Es gibt einen Rabatt, aber er scheint nicht stark genug.",
        "it": "C'è uno sconto, ma non sembra aggressivo.",
        "pt": "Há um desconto, mas não parece ser agressivo.",
        "nl": "Er is korting, maar die lijkt niet agressief genoeg.",
        "tr": "İndirim var, ancak yeterince güçlü değil.",
    },
    "fake_discount_check": {
        "en": "User requested a check for a possible fake discount.",
        "es": "El usuario pidió revisar posible descuento falso.",
        "fr": "L'utilisateur a demandé de vérifier une possible fausse remise.",
        "ar": "طلب المستخدم التحقق من خصم قد يكون مزيفًا.",
        "de": "Der Nutzer bat um Prüfung auf einen möglichen Fake-Rabatt.",
        "it": "L'utente ha richiesto la verifica di un possibile sconto falso.",
        "pt": "O usuário pediu para verificar um possível desconto falso.",
        "nl": "De gebruiker vroeg om controle op een mogelijke neppkorting.",
        "tr": "Kullanıcı olası sahte indirim kontrolü istedi.",
    },
    "specs_detected": {
        "en": "Specs detected: a simple explanation was prepared for an informed purchase.",
        "es": "Specs detectadas: se preparó explicación simple para compra informada.",
        "fr": "Spécifications détectées : une explication simple a été préparée.",
        "ar": "تم اكتشاف المواصفات: تم إعداد شرح بسيط للشراء المستنير.",
        "de": "Technische Daten erkannt: eine einfache Erklärung wurde vorbereitet.",
        "it": "Specifiche rilevate: è stata preparata una spiegazione semplice.",
        "pt": "Especificações detectadas: uma explicação simples foi preparada.",
        "nl": "Specificaties gedetecteerd: een eenvoudige uitleg is voorbereid.",
        "tr": "Özellikler tespit edildi: bilinçli alışveriş için basit açıklama hazırlandı.",
    },
}

_SUGGESTIONS: dict[str, list[str]] = {
    "en": [
        "Compare the price across 2 or 3 stores before paying",
        "Check Hot/Cold ratings and community reviews",
        "Set a price alert if the purchase is not urgent",
        "Verify the seller, warranty, and return policy",
    ],
    "es": [
        "Comparar precio con 2 o 3 tiendas antes de pagar",
        "Revisar Hot/Cold y comentarios de la comunidad",
        "Activar alerta si el precio no es urgente",
        "Comprobar vendedor, garantía y devolución",
    ],
    "fr": [
        "Comparer le prix dans 2 ou 3 boutiques avant d'acheter",
        "Consulter les avis Hot/Cold et de la communauté",
        "Activer une alerte si l'achat n'est pas urgent",
        "Vérifier le vendeur, la garantie et les retours",
    ],
    "ar": [
        "قارن السعر في 2 أو 3 متاجر قبل الدفع",
        "راجع تقييمات Hot/Cold وتعليقات المجتمع",
        "فعّل تنبيه السعر إذا لم يكن الشراء عاجلاً",
        "تحقق من البائع والضمان وسياسة الإرجاع",
    ],
    "de": [
        "Preis in 2 oder 3 Shops vor dem Kauf vergleichen",
        "Hot/Cold-Bewertungen und Community-Meinungen prüfen",
        "Preisalarm setzen, falls kein Eildruck besteht",
        "Anbieter, Garantie und Rückgabe prüfen",
    ],
    "it": [
        "Confronta il prezzo in 2 o 3 negozi prima di pagare",
        "Controlla i voti Hot/Cold e le recensioni della community",
        "Attiva un'allerta se l'acquisto non è urgente",
        "Verifica venditore, garanzia e reso",
    ],
    "pt": [
        "Compare o preço em 2 ou 3 lojas antes de pagar",
        "Verifique as avaliações Hot/Cold e comentários da comunidade",
        "Ative um alerta se a compra não for urgente",
        "Verifique o vendedor, garantia e devolução",
    ],
    "nl": [
        "Vergelijk de prijs in 2 of 3 winkels voor je betaalt",
        "Bekijk Hot/Cold-beoordelingen en gemeenschapsreviews",
        "Stel een prijsalert in als de aankoop niet urgent is",
        "Controleer de verkoper, garantie en het retourbeleid",
    ],
    "tr": [
        "Ödemeden önce fiyatı 2 veya 3 mağazada karşılaştır",
        "Hot/Cold puanlarını ve topluluk yorumlarını kontrol et",
        "Alışveriş acil değilse fiyat alarmı kur",
        "Satıcı, garanti ve iade politikasını doğrula",
    ],
}

_SUMMARIES: dict[str, dict[str, str]] = {
    "buy_now": {
        "en": "Recommended purchase{place}{price}: the discount is strong ({discount}%).",
        "es": "Compra recomendable{place}{price}: el descuento aproximado es fuerte ({discount}%).",
        "fr": "Achat recommandé{place}{price} : la remise est importante ({discount}%).",
        "ar": "شراء موصى به{place}{price}: الخصم قوي ({discount}%).",
        "de": "Empfohlener Kauf{place}{price}: der Rabatt ist stark ({discount}%).",
        "it": "Acquisto consigliato{place}{price}: lo sconto è forte ({discount}%).",
        "pt": "Compra recomendada{place}{price}: o desconto é forte ({discount}%).",
        "nl": "Aanbevolen aankoop{place}{price}: de korting is sterk ({discount}%).",
        "tr": "Önerilen alışveriş{place}{price}: indirim güçlü ({discount}%).",
    },
    "good_deal": {
        "en": "Good deal{place}{price}, but compare one more store before paying.",
        "es": "Buena oferta{place}{price}, pero compara una tienda más antes de pagar.",
        "fr": "Bonne affaire{place}{price}, mais comparez encore une boutique avant de payer.",
        "ar": "صفقة جيدة{place}{price}، لكن قارن متجراً آخر قبل الدفع.",
        "de": "Gutes Angebot{place}{price}, aber vergleiche noch einen Shop vor dem Kauf.",
        "it": "Buona offerta{place}{price}, ma confronta ancora un negozio prima di pagare.",
        "pt": "Bom negócio{place}{price}, mas compare mais uma loja antes de pagar.",
        "nl": "Goede deal{place}{price}, maar vergelijk nog één winkel voor je betaalt.",
        "tr": "İyi fırsat{place}{price}, ancak ödemeden önce bir mağaza daha karşılaştır.",
    },
    "bad_deal": {
        "en": "This does not appear to be a real offer: the old price does not beat the current one.",
        "es": "No parece una oferta real: el precio anterior no mejora el actual.",
        "fr": "Cela ne semble pas être une vraie offre : l'ancien prix n'est pas meilleur.",
        "ar": "لا يبدو أن هذا عرضًا حقيقيًا: السعر القديم لا يتفوق على الحالي.",
        "de": "Das scheint kein echtes Angebot zu sein: der alte Preis ist nicht besser.",
        "it": "Non sembra un'offerta reale: il vecchio prezzo non supera quello attuale.",
        "pt": "Isso não parece uma oferta real: o preço antigo não supera o atual.",
        "nl": "Dit lijkt geen echte aanbieding: de oude prijs is niet beter dan de huidige.",
        "tr": "Bu gerçek bir teklif gibi görünmüyor: eski fiyat mevcut fiyatı geçmiyor.",
    },
    "wait": {
        "en": "Better to wait or set an alert: the discount does not seem strong enough.",
        "es": "Mejor esperar o activar alerta: la rebaja no parece suficientemente fuerte.",
        "fr": "Mieux vaut attendre ou activer une alerte : la remise ne semble pas suffisante.",
        "ar": "من الأفضل الانتظار أو تفعيل تنبيه: الخصم لا يبدو كافياً.",
        "de": "Besser warten oder Alarm setzen: der Rabatt scheint nicht stark genug.",
        "it": "Meglio aspettare o attivare un'allerta: lo sconto non sembra abbastanza forte.",
        "pt": "Melhor esperar ou ativar alerta: o desconto não parece forte o suficiente.",
        "nl": "Beter wachten of een alert instellen: de korting lijkt niet sterk genoeg.",
        "tr": "Beklemek veya alarm kurmak daha iyi: indirim yeterince güçlü görünmüyor.",
    },
    "default": {
        "en": "Analyze price, store, warranty, and reviews before buying.",
        "es": "Analiza precio, tienda, garantía y opiniones antes de comprar.",
        "fr": "Analysez le prix, la boutique, la garantie et les avis avant d'acheter.",
        "ar": "حلل السعر والمتجر والضمان والمراجعات قبل الشراء.",
        "de": "Preis, Shop, Garantie und Bewertungen vor dem Kauf prüfen.",
        "it": "Analizza prezzo, negozio, garanzia e recensioni prima di acquistare.",
        "pt": "Analise preço, loja, garantia e avaliações antes de comprar.",
        "nl": "Analyseer prijs, winkel, garantie en beoordelingen voor je koopt.",
        "tr": "Satın almadan önce fiyat, mağaza, garanti ve yorumları incele.",
    },
}

_ALTERNATIVES_GENERIC: dict[str, list[str]] = {
    "en": ["Search for a refurbished alternative", "Compare with an equivalent brand", "Wait for a verified discount"],
    "es": ["Buscar alternativa reacondicionada", "Comparar con marca equivalente", "Esperar una rebaja verificada"],
    "fr": ["Chercher une alternative reconditionnée", "Comparer avec une marque équivalente", "Attendre une remise vérifiée"],
    "ar": ["ابحث عن بديل مجدد", "قارن مع علامة تجارية مكافئة", "انتظر خصمًا موثقًا"],
    "de": ["Nach einer aufgearbeiteten Alternative suchen", "Mit einer gleichwertigen Marke vergleichen", "Auf einen verifizierten Rabatt warten"],
    "it": ["Cercare un'alternativa ricondizionata", "Confrontare con un marchio equivalente", "Aspettare uno sconto verificato"],
    "pt": ["Buscar alternativa recondicionada", "Comparar com marca equivalente", "Aguardar um desconto verificado"],
    "nl": ["Zoek een gereviseerd alternatief", "Vergelijk met een gelijkwaardig merk", "Wacht op een geverifieerde korting"],
    "tr": ["Yenilenmiş alternatif ara", "Eşdeğer marka ile karşılaştır", "Doğrulanmış indirim bekle"],
}

_SPEC_LABELS: dict[str, dict[str, str]] = {
    "ram": {
        "en": "{spec}: affects fluidity and multitasking.",
        "es": "{spec}: afecta a fluidez y multitarea.",
        "fr": "{spec}: affecte la fluidité et le multitâche.",
        "ar": "{spec}: يؤثر على السلاسة وتعدد المهام.",
        "de": "{spec}: beeinflusst Flüssigkeit und Multitasking.",
        "it": "{spec}: influisce sulla fluidità e il multitasking.",
        "pt": "{spec}: afeta a fluidez e multitarefa.",
        "nl": "{spec}: beïnvloedt vloeiendheid en multitasking.",
        "tr": "{spec}: akıcılığı ve çoklu görevi etkiler.",
    },
    "storage": {
        "en": "{spec}: check if the storage meets your needs for 2-3 years.",
        "es": "{spec}: revisa si el almacenamiento te llega para 2-3 años.",
        "fr": "{spec}: vérifiez si le stockage vous suffit pour 2-3 ans.",
        "ar": "{spec}: تحقق مما إذا كانت سعة التخزين كافية لمدة 2-3 سنوات.",
        "de": "{spec}: prüfe, ob der Speicher für 2-3 Jahre reicht.",
        "it": "{spec}: verifica se lo spazio soddisfa le tue esigenze per 2-3 anni.",
        "pt": "{spec}: verifique se o armazenamento atende às suas necessidades por 2-3 anos.",
        "nl": "{spec}: controleer of de opslag je 2-3 jaar van dienst is.",
        "tr": "{spec}: depolamanın 2-3 yıl ihtiyacınızı karşılayıp karşılamadığını kontrol edin.",
    },
    "hz": {
        "en": "{spec}: smoother display, useful for gaming and scrolling.",
        "es": "{spec}: pantalla más fluida, útil para gaming y scroll.",
        "fr": "{spec}: écran plus fluide, utile pour le gaming et le défilement.",
        "ar": "{spec}: شاشة أكثر سلاسة، مفيدة للألعاب والتصفح.",
        "de": "{spec}: flüssigeres Display, nützlich für Gaming und Scrollen.",
        "it": "{spec}: schermo più fluido, utile per gaming e scorrimento.",
        "pt": "{spec}: tela mais fluida, útil para jogos e rolagem.",
        "nl": "{spec}: vloeiender scherm, handig voor gaming en scrollen.",
        "tr": "{spec}: daha akıcı ekran, oyun ve kaydırma için faydalı.",
    },
    "default": {
        "en": "{spec}: compare with your real use before paying extra.",
        "es": "{spec}: compáralo con tu uso real antes de pagar extra.",
        "fr": "{spec}: comparez avec votre usage réel avant de payer plus.",
        "ar": "{spec}: قارنه مع استخدامك الفعلي قبل دفع المزيد.",
        "de": "{spec}: mit deinem tatsächlichen Nutzungsverhalten vergleichen, bevor du mehr zahlst.",
        "it": "{spec}: confrontalo con il tuo uso reale prima di pagare di più.",
        "pt": "{spec}: compare com seu uso real antes de pagar a mais.",
        "nl": "{spec}: vergelijk met je werkelijk gebruik voor je meer betaalt.",
        "tr": "{spec}: fazla para ödemeden önce gerçek kullanımınızla karşılaştırın.",
    },
}

_PLACE_PREPOSITIONS: dict[str, str] = {
    "en": " at", "es": " en", "fr": " chez", "ar": " في",
    "de": " bei", "it": " da", "pt": " em", "nl": " bij", "tr": "",
}

_PRICE_PREPOSITIONS: dict[str, str] = {
    "en": " for", "es": " por", "fr": " pour", "ar": " بـ",
    "de": " für", "it": " per", "pt": " por", "nl": " voor", "tr": "",
}


def _reason(key: str, lang: str, **kwargs: Any) -> str:
    table = _REASONS.get(key, {})
    template = table.get(lang) or table.get("en") or key
    return template.format(**kwargs) if kwargs else template


def _summary_text(verdict: str, lang: str, place: str, price: str, discount: int) -> str:
    table = _SUMMARIES.get(verdict, _SUMMARIES["default"])
    template = table.get(lang) or table.get("en") or ""
    return template.format(place=place, price=price, discount=discount)


class AIBrainService:
    """Authenticated Deal Brain: deterministic rules with an optional,
    locale-aware LLM summary layered on top."""

    async def analyze(self, payload, current_user: dict) -> dict:
        base = self._rules_analysis(payload)
        llm_text = await self._llm_summary(payload, base)
        if llm_text:
            base["summary"] = llm_text
            base["model_used"] = os.getenv("GROQ_MODEL", "groq")
        saved = await asyncio.to_thread(
            ai_brain_repository.save,
            user_id=current_user["uid"],
            payload=payload.model_dump(),
            result=base,
        )
        return saved

    async def history(self, current_user: dict, limit: int = 30) -> dict:
        items = await asyncio.to_thread(
            ai_brain_repository.history,
            user_id=current_user["uid"],
            limit=limit,
        )
        return {"items": items}

    def _rules_analysis(self, payload) -> dict:
        lang = get_locale().language
        query = payload.query.strip().lower()
        current = payload.current_price
        old = payload.old_price
        discount = 0
        savings = 0.0

        if current and old and old > current:
            discount = int(((old - current) / old) * 100)
            savings = float(old - current)

        score = DealScoreService.calculate_score(current_price=current or 0, old_price=old)
        fake_risk = FakeDiscountService.detect_risk(current_price=current or 0, old_price=old)
        risk = "low"
        verdict = "compare"
        best_action = "compare_more"
        price_signal = "unknown"
        confidence = 72
        fair_price = None
        reasons: list[str] = []

        if old and current:
            fair_price = round((old + current) / 2, 2) if old > current else current
            if old <= current:
                verdict = "bad_deal"
                risk = "medium"
                price_signal = "price_not_lower"
                best_action = "wait"
                confidence = 80
                reasons.append(_reason("price_not_lower", lang))
            elif discount >= 35:
                verdict = "buy_now"
                price_signal = "strong_drop"
                best_action = "buy_if_needed"
                confidence = 88
                reasons.append(_reason("strong_discount", lang, discount=discount))
            elif discount >= 15:
                verdict = "good_deal"
                price_signal = "fair_drop"
                best_action = "compare_then_buy"
                confidence = 78
                reasons.append(_reason("fair_discount", lang, discount=discount))
            else:
                verdict = "wait"
                price_signal = "small_drop"
                best_action = "add_to_watchlist"
                reasons.append(_reason("small_discount", lang))

        fake_keywords = {"fake", "falso", "engaño", "estafa", "مزيف", "faux", "sahte"}
        if any(word in query for word in fake_keywords):
            risk = "medium" if risk == "low" else risk
            verdict = "check_discount"
            best_action = "verify_history"
            reasons.append(_reason("fake_discount_check", lang))

        if payload.specs:
            reasons.append(_reason("specs_detected", lang))

        suggestions = _SUGGESTIONS.get(lang) or _SUGGESTIONS["en"]
        alternatives = self._alternatives(payload, lang)
        specs_explained = self._explain_specs(payload.specs or "", lang)
        summary = self._summary(verdict, discount, payload.store, current, payload.currency, lang)

        return {
            "intent": self._detect_intent(query),
            "verdict": verdict,
            "score": int(max(0, min(100, score))),
            "confidence": int(confidence),
            "summary": summary,
            "suggestions": suggestions,
            "risk_level": risk,
            "fake_discount_risk": fake_risk,
            "price_signal": price_signal,
            "best_action": best_action,
            "savings_estimate": round(savings, 2),
            "fair_price_estimate": fair_price,
            "alternatives": alternatives,
            "specs_explained": specs_explained,
            "reasons": reasons,
            "model_used": "rules_plus_llm_optional",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _llm_summary(self, payload, base: dict) -> str:
        if not os.getenv("GROQ_API_KEY"):
            return ""
        locale = get_locale().merged_with(
            language=payload.language,
            country=payload.country,
            currency=payload.currency,
            allow_auto=True,
        )
        prompt = (
            "Act as an expert shopper. In at most 70 words, say whether buying is "
            f"worth it. Write the answer in {locale.display_name}. Do not invent "
            "data. Use a clear, direct tone. Data: "
            f"query={payload.query}; title={payload.title}; store={payload.store}; "
            f"price={payload.current_price}; old={payload.old_price}; "
            f"verdict={base.get('verdict')}; risk={base.get('risk_level')}"
        )
        try:
            result = await ai_service.analyze_query(
                query=prompt,
                country_code=payload.country,
                currency=payload.currency,
                language=payload.language,
            )
            answer = result.get("answer") or result.get("summary") or ""
            return str(answer).strip()[:700]
        except Exception:
            return ""

    def _detect_intent(self, query: str) -> str:
        if any(x in query for x in ["coupon", "cupón", "cupon", "كوبون", "coupon"]):
            return "coupon_search"
        if any(x in query for x in ["fake", "falso", "engaño", "estafa", "مزيف", "faux", "sahte"]):
            return "fake_discount_check"
        if any(x in query for x in ["compare", "comparar", "mejor", "قارن", "comparer", "vergleich"]):
            return "compare_products"
        if any(x in query for x in ["spec", "specs", "característica", "ram", "procesador", "مواصفات", "spezifikation"]):
            return "specs_translator"
        return "shopping_advice"

    def _summary(
        self,
        verdict: str,
        discount: int,
        store: str | None,
        current: float | None,
        currency: str,
        lang: str,
    ) -> str:
        prep_place = _PLACE_PREPOSITIONS.get(lang, " at")
        prep_price = _PRICE_PREPOSITIONS.get(lang, " for")
        place = f"{prep_place} {store}" if store else ""
        price = f"{prep_price} {current:.2f} {currency}" if current else ""
        return _summary_text(verdict, lang, place, price, discount)

    def _alternatives(self, payload, lang: str) -> list[str]:
        title = (payload.title or payload.query or "").strip()
        if not title:
            return _ALTERNATIVES_GENERIC.get(lang) or _ALTERNATIVES_GENERIC["en"]

        patterns: dict[str, list[str]] = {
            "en": [
                f"Search for refurbished {title} with warranty",
                f"Compare {title} on Amazon, MediaMarkt and PcComponentes",
                f"Create a price alert for {title}",
            ],
            "es": [
                f"Buscar {title} reacondicionado con garantía",
                f"Comparar {title} en Amazon, MediaMarkt y PcComponentes",
                f"Crear alerta de precio para {title}",
            ],
            "fr": [
                f"Chercher {title} reconditionné avec garantie",
                f"Comparer {title} sur Amazon, MediaMarkt et PcComponentes",
                f"Créer une alerte de prix pour {title}",
            ],
            "ar": [
                f"ابحث عن {title} مجدد مع ضمان",
                f"قارن {title} على Amazon وMediaMarkt وPcComponentes",
                f"أنشئ تنبيه سعر لـ {title}",
            ],
            "de": [
                f"Aufgearbeitetes {title} mit Garantie suchen",
                f"{title} auf Amazon, MediaMarkt und PcComponentes vergleichen",
                f"Preisalarm für {title} erstellen",
            ],
            "it": [
                f"Cercare {title} ricondizionato con garanzia",
                f"Confrontare {title} su Amazon, MediaMarkt e PcComponentes",
                f"Creare un'allerta di prezzo per {title}",
            ],
            "pt": [
                f"Buscar {title} recondicionado com garantia",
                f"Comparar {title} na Amazon, MediaMarkt e PcComponentes",
                f"Criar alerta de preço para {title}",
            ],
            "nl": [
                f"Gereviseerde {title} met garantie zoeken",
                f"{title} vergelijken op Amazon, MediaMarkt en PcComponentes",
                f"Prijsalert aanmaken voor {title}",
            ],
            "tr": [
                f"Garantili yenilenmiş {title} ara",
                f"{title}'ı Amazon, MediaMarkt ve PcComponentes'te karşılaştır",
                f"{title} için fiyat alarmı oluştur",
            ],
        }
        return patterns.get(lang) or patterns["en"]

    def _explain_specs(self, specs: str, lang: str) -> list[str]:
        if not specs.strip():
            return []
        parts = [x.strip() for x in specs.replace("\n", ",").split(",") if x.strip()]
        explanations = []
        for part in parts[:5]:
            lower = part.lower()
            if "ram" in lower:
                key = "ram"
            elif "gb" in lower or "tb" in lower:
                key = "storage"
            elif "hz" in lower:
                key = "hz"
            else:
                key = "default"
            table = _SPEC_LABELS[key]
            template = table.get(lang) or table.get("en") or ""
            explanations.append(template.format(spec=part))
        return explanations


ai_brain_service = AIBrainService()
