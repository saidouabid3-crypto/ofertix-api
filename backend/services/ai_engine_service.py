from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from core.locale_context import get_locale
from schemas.ai_deal_brain import (
    AnalyzeGlobalRequest,
    CustomsHoldRisk,
    CustomsRiskCard,
    DarkPatternSignal,
    DarkPatternsCard,
    DiscountCurrencyCard,
    GlobalAlternativeCard,
    GlobalDealAnalysisResponse,
    HumanSpecItem,
    HumanSpecsCard,
    Importance,
    LegitimacyLevel,
    MetaCard,
    Money,
    NegotiationCard,
    NegotiationRequest,
    PriceForecastCard,
    ProductInput,
    RiskLevel,
    TrafficColor,
    TrendDirection,
    VerdictCard,
    VerdictCommand,
)
from services.currency_service import currency_service
from services.llm_transport import llm_transport
from services.locale_prompt_engine import locale_prompt_engine

logger = logging.getLogger("ofertix.ai.engine")


class AiEngineService:
    """Deterministic + LLM-enhanced engine for AI Deal Brain Pro.

    The deterministic mathematics (customs, forecast, fair price, fake-discount
    and urgency scoring, and the fully localized fallback verdict) are the
    proven core and are preserved here. The LLM enhancement now flows through
    the single :data:`~services.llm_transport.llm_transport` and the dynamic
    :data:`~services.locale_prompt_engine.locale_prompt_engine`, so the active
    request locale (from the middleware contextvar) drives the language of every
    AI-produced string while JSON keys/enums stay English.
    """

    async def analyze_global(
        self, request: AnalyzeGlobalRequest
    ) -> GlobalDealAnalysisResponse:
        payload = await self._build_payload(request)

        # Request-body values win over header-derived context for this call.
        locale = get_locale().merged_with(
            language=request.user.language,
            country=request.user.country,
            currency=request.user.currency,
        )

        if llm_transport.is_configured():
            try:
                system_prompt = locale_prompt_engine.build_global_deal_system_prompt(
                    locale
                )
                raw = await llm_transport.complete_json(
                    system_prompt=system_prompt,
                    user_content=json.dumps(payload, ensure_ascii=False),
                    temperature=0.2,
                )
                parsed = self._parse_response(raw, request)
                return self._merge_with_safe_defaults(parsed, request, payload)
            except Exception as exc:  # noqa: BLE001 - fall back deterministically
                logger.warning(
                    "LLM analysis failed; deterministic fallback used: %s", exc
                )

        return self._deterministic_analysis(request, payload)

    async def generate_negotiation(self, request: NegotiationRequest) -> str:
        fallback = self._fallback_negotiation_script(request)
        if not llm_transport.is_configured():
            return fallback

        system_prompt = locale_prompt_engine.build_negotiation_system_prompt(
            request.sellerLanguage
        )
        user_content = json.dumps(
            {
                "task": "generate_seller_negotiation_script",
                "input": request.model_dump(),
            },
            ensure_ascii=False,
        )

        try:
            result = (
                await llm_transport.complete_text(
                    system_prompt=system_prompt,
                    user_content=user_content,
                    temperature=0.35,
                )
            ).strip()
            return result[:1200] if result else fallback
        except Exception as exc:  # noqa: BLE001
            logger.warning("Negotiation LLM failed; fallback used: %s", exc)
            return fallback

    async def _build_payload(self, request: AnalyzeGlobalRequest) -> dict[str, Any]:
        product = request.product
        user = request.user

        converted_price = await currency_service.convert(
            product.currentPrice,
            product.baseCurrency,
            user.currency,
        )
        converted_shipping = await currency_service.convert(
            product.shippingPrice or 0,
            product.baseCurrency,
            user.currency,
        )
        customs = self._estimate_customs_risk(
            product, user.country, converted_price + converted_shipping, user.currency
        )
        total_landed_cost = round(
            converted_price + converted_shipping + customs["estimated_extra_cost"], 2
        )
        advertised_discount = self._advertised_discount(product)
        fake_discount_risk = self._fake_discount_risk(product, advertised_discount)
        dark_score = self._urgency_legitimacy_score(product.darkPatternSignals)
        forecast = self._forecast_price(product, advertised_discount, fake_discount_risk)
        fair_price = self._estimate_fair_price(
            product, converted_price, converted_shipping, customs["estimated_extra_cost"]
        )

        return {
            "product": product.model_dump(),
            "user": user.model_dump(),
            "computed": {
                "convertedProductPrice": converted_price,
                "convertedShipping": converted_shipping,
                "estimatedTax": customs["estimated_extra_cost"],
                "estimatedCustomsHoldRisk": customs["hold_risk"],
                "tariffRiskPercent": customs["tariff_risk_percent"],
                "totalLandedCost": total_landed_cost,
                "advertisedDiscountPercent": advertised_discount,
                "realisticDiscountPercent": max(0, min(advertised_discount, 70)),
                "fakeDiscountRisk": fake_discount_risk,
                "urgencyLegitimacyScore": dark_score,
                "priceForecast": forecast,
                "fairPrice": fair_price,
            },
        }

    def _estimate_customs_risk(
        self,
        product: ProductInput,
        user_country: str,
        subtotal_local: float,
        user_currency: str,
    ) -> dict[str, Any]:
        store_country = product.storeCountry.upper()
        user_country = user_country.upper()
        eu_countries = {
            "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
            "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
            "RO", "SK", "SI", "ES", "SE",
        }

        cross_border = store_country != user_country

        if not cross_border or (
            store_country in eu_countries and user_country in eu_countries
        ):
            return {
                "hold_risk": CustomsHoldRisk.LOW.value,
                "tariff_risk_percent": 5,
                "estimated_extra_cost": 0.0,
                "currency": user_currency,
            }

        category = (product.category or product.title or "").lower()
        heavy_or_large = bool(product.weightKg and product.weightKg > 2.0) or bool(
            product.dimensions
        )
        electronics = any(
            term in category
            for term in [
                "phone", "smartphone", "laptop", "tablet", "camera", "drone",
                "electronics",
            ]
        )
        fashion = any(
            term in category
            for term in ["shoe", "shoes", "clothes", "fashion", "bag", "watch"]
        )

        base_percent = 21 if user_country in eu_countries else 15
        hold_risk = 38

        if subtotal_local > 150:
            hold_risk += 25
            base_percent += 4
        if electronics:
            hold_risk += 16
            base_percent += 3
        if fashion:
            hold_risk += 10
        if heavy_or_large:
            hold_risk += 12
            base_percent += 2
        if store_country in {"CN", "US"} and user_country in eu_countries:
            hold_risk += 10

        hold_risk = max(0, min(hold_risk, 95))
        extra_cost = round(max(0, subtotal_local * (base_percent / 100)), 2)

        risk_label = (
            CustomsHoldRisk.HIGH.value
            if hold_risk >= 65
            else CustomsHoldRisk.MEDIUM.value
            if hold_risk >= 30
            else CustomsHoldRisk.LOW.value
        )

        return {
            "hold_risk": risk_label,
            "tariff_risk_percent": hold_risk,
            "estimated_extra_cost": extra_cost,
            "currency": user_currency,
        }

    def _forecast_price(
        self,
        product: ProductInput,
        advertised_discount: int,
        fake_discount_risk: int,
    ) -> dict[str, Any]:
        title = (product.title or "").lower()
        store = (product.store or "").lower()
        category = (product.category or "").lower()
        seasonal_drop_terms = [
            "phone", "smartphone", "case", "headphone", "earbuds", "fashion",
            "shoes", "clothes",
        ]
        volatile_store = any(
            name in store for name in ["aliexpress", "temu", "shein", "dhgate"]
        )

        probability = 45
        expected_change = 0.0
        trend = TrendDirection.STABLE.value

        if volatile_store:
            probability += 15
            expected_change -= 5
            trend = TrendDirection.DROP_LIKELY.value

        if advertised_discount >= 50 or fake_discount_risk >= 60:
            probability += 12
            expected_change -= 7
            trend = TrendDirection.DROP_LIKELY.value

        if any(term in title or term in category for term in seasonal_drop_terms):
            probability += 8
            expected_change -= 4
            trend = TrendDirection.DROP_LIKELY.value

        if product.reviewCount is not None and product.reviewCount < 15:
            probability -= 8

        probability = max(25, min(probability, 85))
        expected_change = round(expected_change, 1)

        return {
            "trend": trend,
            "probabilityPercent": probability,
            "expectedChangePercent": expected_change,
            "horizonDays": 14,
        }

    def _estimate_fair_price(
        self,
        product: ProductInput,
        converted_price: float,
        converted_shipping: float,
        taxes: float,
    ) -> float:
        if converted_price <= 0:
            return 0.0
        fair = converted_price
        if product.oldPrice and product.oldPrice > product.currentPrice:
            advertised = self._advertised_discount(product)
            if advertised >= 60:
                fair *= 0.90
            elif advertised >= 40:
                fair *= 0.95
        if product.rating is not None and product.rating < 3.8:
            fair *= 0.88
        if product.reviewCount is not None and product.reviewCount < 20:
            fair *= 0.92
        if converted_shipping + taxes > converted_price * 0.35:
            fair *= 0.86
        return round(max(fair, 0), 2)

    def _advertised_discount(self, product: ProductInput) -> int:
        if (
            not product.oldPrice
            or product.oldPrice <= product.currentPrice
            or product.oldPrice <= 0
        ):
            return 0
        return round(
            ((product.oldPrice - product.currentPrice) / product.oldPrice) * 100
        )

    def _fake_discount_risk(self, product: ProductInput, advertised_discount: int) -> int:
        risk = 20
        if advertised_discount >= 70:
            risk += 55
        elif advertised_discount >= 50:
            risk += 35
        elif advertised_discount >= 30:
            risk += 15

        if product.reviewCount is not None and product.reviewCount < 20:
            risk += 15
        if product.rating is not None and product.rating < 3.8:
            risk += 15
        if not product.oldPrice:
            risk += 10
        if any(signal.severity >= 70 for signal in product.darkPatternSignals):
            risk += 8

        return max(0, min(risk, 100))

    def _urgency_legitimacy_score(self, signals: list[DarkPatternSignal]) -> int:
        if not signals:
            return 82
        penalty = sum(
            max(0, min(signal.severity, 100)) for signal in signals[:8]
        ) / max(len(signals[:8]), 1)
        score = round(100 - penalty * 0.75)
        return max(0, min(score, 100))

    def _parse_response(
        self, raw: str, request: AnalyzeGlobalRequest
    ) -> GlobalDealAnalysisResponse:
        json_text = self._extract_json_object(raw)
        data = json.loads(json_text)
        try:
            return GlobalDealAnalysisResponse.model_validate(data)
        except ValidationError as exc:
            logger.warning("Strict JSON validation failed; repairing response: %s", exc)
            return self._repair_partial_response(data, request)

    def _extract_json_object(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("{") and raw.endswith("}"):
            return raw
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise ValueError("LLM response did not contain a JSON object.")
        return match.group(0)

    def _repair_partial_response(
        self,
        data: dict[str, Any],
        request: AnalyzeGlobalRequest,
    ) -> GlobalDealAnalysisResponse:
        fallback = self._deterministic_analysis(request, {})
        merged = fallback.model_dump()
        for key in (
            "meta",
            "verdictCard",
            "discountCurrencyCard",
            "humanSpecsCard",
            "globalAlternativeCard",
            "darkPatternsCard",
            "priceForecastCard",
            "customsRiskCard",
            "negotiation",
        ):
            if isinstance(data.get(key), dict):
                merged[key].update(data[key])
        return GlobalDealAnalysisResponse.model_validate(merged)

    def _merge_with_safe_defaults(
        self,
        parsed: GlobalDealAnalysisResponse,
        request: AnalyzeGlobalRequest,
        payload: dict[str, Any],
    ) -> GlobalDealAnalysisResponse:
        product = request.product
        user = request.user
        computed = payload.get("computed", {})

        parsed.meta.userLanguage = parsed.meta.userLanguage or user.language
        parsed.meta.userCountry = parsed.meta.userCountry or user.country
        parsed.meta.userCurrency = parsed.meta.userCurrency or user.currency
        parsed.meta.store = parsed.meta.store or product.store
        parsed.meta.storeCountry = parsed.meta.storeCountry or product.storeCountry
        parsed.meta.sellerLanguage = parsed.meta.sellerLanguage or product.sellerLanguage

        if parsed.discountCurrencyCard.totalLandedCost.amount <= 0:
            parsed.discountCurrencyCard.totalLandedCost = Money(
                amount=float(computed.get("totalLandedCost", 0)),
                currency=user.currency,
            )

        if parsed.customsRiskCard.estimatedExtraCost.amount <= 0 and float(
            computed.get("estimatedTax", 0)
        ) > 0:
            parsed.customsRiskCard.estimatedExtraCost = Money(
                amount=float(computed.get("estimatedTax", 0)),
                currency=user.currency,
            )

        if not parsed.darkPatternsCard.detectedSignals and product.darkPatternSignals:
            parsed.darkPatternsCard.detectedSignals = product.darkPatternSignals

        if not parsed.negotiation.script:
            parsed.negotiation.script = self._fallback_negotiation_script(
                NegotiationRequest(
                    productTitle=product.title,
                    store=product.store,
                    sellerLanguage=product.sellerLanguage,
                    userLanguage=user.language,
                    userCountry=user.country,
                    currentTotalCost=parsed.discountCurrencyCard.totalLandedCost,
                    targetPrice=parsed.negotiation.targetPrice,
                    reason=parsed.negotiation.reason,
                )
            )

        return parsed

    def _deterministic_analysis(
        self,
        request: AnalyzeGlobalRequest,
        payload: dict[str, Any],
    ) -> GlobalDealAnalysisResponse:
        product = request.product
        user = request.user
        computed = payload.get("computed", {}) if payload else {}

        converted = float(computed.get("convertedProductPrice", product.currentPrice))
        shipping = float(computed.get("convertedShipping", product.shippingPrice or 0))
        taxes = float(computed.get("estimatedTax", 0))
        total = float(computed.get("totalLandedCost", converted + shipping + taxes))
        advertised = int(
            computed.get("advertisedDiscountPercent", self._advertised_discount(product))
        )
        fake_risk = int(
            computed.get("fakeDiscountRisk", self._fake_discount_risk(product, advertised))
        )
        urgency_score = int(
            computed.get(
                "urgencyLegitimacyScore",
                self._urgency_legitimacy_score(product.darkPatternSignals),
            )
        )
        forecast = computed.get("priceForecast") or self._forecast_price(
            product, advertised, fake_risk
        )
        customs = self._estimate_customs_risk(
            product, user.country, converted + shipping, user.currency
        )
        fair_price = float(
            computed.get(
                "fairPrice",
                self._estimate_fair_price(product, converted, shipping, taxes),
            )
        )

        score = 72
        if fake_risk >= 70:
            score -= 25
        elif fake_risk >= 45:
            score -= 12
        if urgency_score < 45:
            score -= 15
        if converted > 0 and shipping + taxes > converted * 0.35:
            score -= 20
        if product.rating is not None and product.rating < 3.8:
            score -= 12
        if product.reviewCount is not None and product.reviewCount < 20:
            score -= 8
        if total > 0 and fair_price > 0 and total > fair_price * 1.25:
            score -= 15
        if not product.title or product.currentPrice <= 0:
            score = 42

        score = max(0, min(score, 100))
        command = (
            VerdictCommand.BUY_NOW
            if score >= 72
            else VerdictCommand.WAIT
            if score >= 52
            else VerdictCommand.AVOID
        )
        color = (
            TrafficColor.GREEN
            if score >= 72
            else TrafficColor.YELLOW
            if score >= 52
            else TrafficColor.RED
        )
        risk = (
            RiskLevel.LOW
            if score >= 72
            else RiskLevel.MEDIUM
            if score >= 52
            else RiskLevel.HIGH
        )
        text = self._localized_text(user.language, command)

        target = round(max(total * 0.88, converted * 0.85), 2)

        negotiation = NegotiationCard(
            shouldShowButton=score < 80 or fake_risk > 45 or urgency_score < 60,
            targetPrice=Money(amount=target, currency=user.currency),
            sellerLanguage=product.sellerLanguage,
            reason=text["negotiation_reason"],
            script="",
        )
        negotiation.script = self._fallback_negotiation_script(
            NegotiationRequest(
                productTitle=product.title,
                store=product.store,
                sellerLanguage=product.sellerLanguage,
                userLanguage=user.language,
                userCountry=user.country,
                currentTotalCost=Money(amount=total, currency=user.currency),
                targetPrice=negotiation.targetPrice,
                reason=negotiation.reason,
            )
        )

        legitimacy = (
            LegitimacyLevel.LEGITIMATE
            if urgency_score >= 70
            else LegitimacyLevel.SUSPICIOUS
            if urgency_score >= 40
            else LegitimacyLevel.MANIPULATIVE
        )

        return GlobalDealAnalysisResponse(
            meta=MetaCard(
                userLanguage=user.language,
                userCountry=user.country,
                userCurrency=user.currency,
                store=product.store,
                storeCountry=product.storeCountry,
                sellerLanguage=product.sellerLanguage,
                confidence=60 if product.currentPrice > 0 else 35,
            ),
            verdictCard=VerdictCard(
                command=command,
                title=text["title"],
                oneLine=text["one_line"],
                score=score,
                riskLevel=risk,
                color=color,
                explanation=text["explanation"],
            ),
            discountCurrencyCard=DiscountCurrencyCard(
                advertisedDiscountPercent=advertised,
                realisticDiscountPercent=max(0, min(advertised, 70)),
                fakeDiscountRisk=fake_risk,
                storePrice=Money(
                    amount=product.currentPrice, currency=product.baseCurrency
                ),
                convertedProductPrice=Money(amount=converted, currency=user.currency),
                estimatedShipping=Money(amount=shipping, currency=user.currency),
                estimatedTaxes=Money(amount=taxes, currency=user.currency),
                estimatedTaxesConfidence=45 if taxes > 0 else 30,
                totalLandedCost=Money(amount=total, currency=user.currency),
                realSaving=Money(
                    amount=max(
                        0,
                        (product.oldPrice or product.currentPrice)
                        - product.currentPrice,
                    ),
                    currency=product.baseCurrency,
                ),
                explanation=text["discount_explanation"],
            ),
            humanSpecsCard=HumanSpecsCard(
                summary=text["specs_summary"],
                items=self._human_specs(product.specs, user.language),
            ),
            globalAlternativeCard=GlobalAlternativeCard(
                title="",
                store="",
                estimatedTotalCost=Money(amount=0, currency=user.currency),
                whyBetter=text["alternative"],
                shippingAdvantage=text["shipping_advantage"],
                url="",
                confidence=0,
            ),
            darkPatternsCard=DarkPatternsCard(
                urgencyLegitimacyScore=urgency_score,
                legitimacyLevel=legitimacy,
                detectedSignals=product.darkPatternSignals[:12],
                explanation=text["dark_patterns"].format(
                    count=len(product.darkPatternSignals)
                ),
                shopperAdvice=text["dark_patterns_advice"],
            ),
            priceForecastCard=PriceForecastCard(
                trend=TrendDirection(forecast.get("trend", TrendDirection.UNKNOWN.value)),
                probabilityPercent=int(forecast.get("probabilityPercent", 50)),
                expectedChangePercent=float(forecast.get("expectedChangePercent", 0)),
                horizonDays=int(forecast.get("horizonDays", 14)),
                explanation=text["forecast_explanation"],
                bestAction=text["forecast_action"],
            ),
            customsRiskCard=CustomsRiskCard(
                holdRisk=CustomsHoldRisk(customs["hold_risk"]),
                tariffRiskPercent=int(customs["tariff_risk_percent"]),
                estimatedExtraCost=Money(
                    amount=float(customs["estimated_extra_cost"]),
                    currency=user.currency,
                ),
                explanation=text["customs_explanation"],
                documentsAdvice=text["customs_advice"],
            ),
            negotiation=negotiation,
        )

    def _localized_text(self, language: str, command: VerdictCommand) -> dict[str, str]:
        lang = (language or "en").split("-")[0].lower()
        if lang == "es":
            return {
                "title": "Cómpralo"
                if command == VerdictCommand.BUY_NOW
                else "Espera"
                if command == VerdictCommand.WAIT
                else "Evítalo",
                "one_line": "La decisión depende del coste final, no del descuento anunciado.",
                "explanation": "He calculado el precio total con envío, impuestos estimados, riesgo de aduana, señales de urgencia artificial y calidad de la oferta.",
                "discount_explanation": "El descuento puede ser menos real si el precio anterior estaba inflado o si envío e impuestos destruyen el ahorro.",
                "specs_summary": "Las especificaciones se han traducido a beneficios reales para comprar con menos confusión.",
                "alternative": "Compara con una tienda local o europea si la importación encarece demasiado la compra.",
                "shipping_advantage": "Una alternativa más cercana puede ahorrar entrega, impuestos y problemas de devolución.",
                "dark_patterns": "Se detectaron {count} señales de urgencia o presión comercial.",
                "dark_patterns_advice": "No compres por presión. Espera unos minutos y compara el coste final.",
                "forecast_explanation": "La previsión usa señales de tienda, descuento y volatilidad. No es certeza, es probabilidad.",
                "forecast_action": "Si no lo necesitas hoy, vigila el precio durante 7-14 días.",
                "customs_explanation": "El riesgo de aduana se estima según país de origen, destino, precio, categoría y tamaño.",
                "customs_advice": "Verifica factura, garantía, devolución y posibles gastos de importación.",
                "negotiation_reason": "El coste final deja margen para pedir una mejora.",
            }
        if lang == "fr":
            return {
                "title": "Acheter"
                if command == VerdictCommand.BUY_NOW
                else "Attendre"
                if command == VerdictCommand.WAIT
                else "Éviter",
                "one_line": "La décision dépend du coût final, pas seulement de la remise affichée.",
                "explanation": "J’ai estimé prix total, livraison, taxes, risque douanier, urgence artificielle et qualité de l’offre.",
                "discount_explanation": "La remise peut être moins réelle si l’ancien prix est gonflé ou si livraison/taxes annulent l’économie.",
                "specs_summary": "Les caractéristiques sont traduites en bénéfices concrets.",
                "alternative": "Comparez avec une boutique locale ou européenne si l’import devient trop cher.",
                "shipping_advantage": "Une option plus proche peut réduire délai, taxes et retours compliqués.",
                "dark_patterns": "{count} signaux d’urgence ou de pression commerciale ont été détectés.",
                "dark_patterns_advice": "N’achetez pas sous pression. Comparez le coût final.",
                "forecast_explanation": "La prévision utilise boutique, remise et volatilité. C’est une probabilité, pas une certitude.",
                "forecast_action": "Si ce n’est pas urgent, surveillez le prix pendant 7 à 14 jours.",
                "customs_explanation": "Le risque douanier dépend du pays, du prix, de la catégorie et du volume.",
                "customs_advice": "Vérifiez facture, garantie, retours et frais d’importation.",
                "negotiation_reason": "Le coût final justifie une demande de meilleur prix.",
            }
        if lang == "ar":
            return {
                "title": "اشترِ الآن"
                if command == VerdictCommand.BUY_NOW
                else "انتظر"
                if command == VerdictCommand.WAIT
                else "تجنّبه",
                "one_line": "القرار يعتمد على التكلفة النهائية وليس التخفيض المعلن فقط.",
                "explanation": "تم تقدير السعر النهائي مع الشحن والضرائب وخطر الجمارك وإشارات الضغط التجاري وجودة العرض.",
                "discount_explanation": "قد يكون التخفيض غير حقيقي إذا كان السعر القديم منفوخًا أو إذا ألغت الشحن والضرائب قيمة التوفير.",
                "specs_summary": "تم تحويل المواصفات التقنية إلى فوائد مفهومة في الحياة اليومية.",
                "alternative": "قارن مع متجر محلي أو أقرب إذا كانت تكلفة الاستيراد مرتفعة.",
                "shipping_advantage": "المتجر الأقرب قد يوفر وقت التوصيل والضرائب ومشاكل الإرجاع.",
                "dark_patterns": "تم اكتشاف {count} إشارات استعجال أو ضغط تجاري.",
                "dark_patterns_advice": "لا تشترِ تحت الضغط. خذ وقتك وقارن التكلفة النهائية.",
                "forecast_explanation": "التوقع يعتمد على إشارات المتجر والتخفيض وتقلب السعر. هو احتمال وليس يقينًا.",
                "forecast_action": "إذا لم تكن محتاجًا للمنتج اليوم، راقب السعر 7 إلى 14 يومًا.",
                "customs_explanation": "مخاطر الجمارك تُقدّر حسب بلد البائع وبلدك والسعر والفئة والحجم.",
                "customs_advice": "تحقق من الفاتورة والضمان وسياسة الإرجاع ومصاريف الاستيراد.",
                "negotiation_reason": "التكلفة النهائية تعطيك سببًا لطلب تخفيض.",
            }
        return {
            "title": "Buy it"
            if command == VerdictCommand.BUY_NOW
            else "Wait"
            if command == VerdictCommand.WAIT
            else "Avoid it",
            "one_line": "The decision depends on final landed cost, not only the advertised discount.",
            "explanation": "I estimated total price, shipping, taxes, customs risk, artificial urgency signals, and deal quality.",
            "discount_explanation": "The discount may be less real if the old price was inflated or shipping/taxes destroy the saving.",
            "specs_summary": "Technical specs are translated into real shopping benefits.",
            "alternative": "Compare with a local or regional store if importing makes this too expensive.",
            "shipping_advantage": "A closer option can reduce delivery time, taxes, and return problems.",
            "dark_patterns": "{count} urgency or commercial pressure signals were detected.",
            "dark_patterns_advice": "Do not buy under pressure. Pause and compare the final cost.",
            "forecast_explanation": "The forecast uses store behavior, discount risk, and volatility. It is probability, not certainty.",
            "forecast_action": "If you do not need it today, watch the price for 7-14 days.",
            "customs_explanation": "Customs risk is estimated from origin, destination, price, category, weight, and size.",
            "customs_advice": "Verify invoice, warranty, returns, and possible import costs.",
            "negotiation_reason": "The final cost leaves room to ask for a better price.",
        }

    def _human_specs(self, specs: str, language: str) -> list[HumanSpecItem]:
        if not specs.strip():
            return [
                HumanSpecItem(
                    spec="Specs",
                    humanMeaning={
                        "es": "Añade especificaciones para obtener una explicación más precisa.",
                        "fr": "Ajoutez les caractéristiques pour une meilleure explication.",
                        "ar": "أضف المواصفات للحصول على تحليل أدق.",
                    }.get(
                        (language or "en").split("-")[0],
                        "Add specs for a more precise explanation.",
                    ),
                    importance=Importance.MEDIUM,
                )
            ]

        chunks = [
            part.strip() for part in re.split(r"[,\n;•|]", specs) if part.strip()
        ][:6]
        items: list[HumanSpecItem] = []
        for chunk in chunks:
            lower = chunk.lower()
            if "mah" in lower:
                meaning = "Battery capacity: usually means longer use, but real life depends on screen, chip, and apps."
                importance = Importance.HIGH
            elif "gb" in lower or "tb" in lower:
                meaning = "Storage or memory: more room for apps, photos, and smoother multitasking."
                importance = Importance.HIGH
            elif "hz" in lower:
                meaning = "Refresh rate: smoother movement for scrolling and gaming."
                importance = Importance.MEDIUM
            elif re.search(r"\b\d+\s*w\b", lower):
                meaning = "Charging or power rating: useful only if the device and charger support it."
                importance = Importance.MEDIUM
            else:
                meaning = "Compare this spec with real reviews before paying extra for it."
                importance = Importance.MEDIUM
            items.append(
                HumanSpecItem(spec=chunk[:160], humanMeaning=meaning, importance=importance)
            )
        return items

    def _fallback_negotiation_script(self, request: NegotiationRequest) -> str:
        lang = (request.sellerLanguage or "en").split("-")[0].lower()
        product = request.productTitle or "this item"
        target = f"{request.targetPrice.amount:.2f} {request.targetPrice.currency}"

        if lang == "es":
            return (
                f"Hola, me interesa bastante {product}. "
                f"Con el coste final se me queda algo alto. "
                f"¿Podrías ajustar el precio cerca de {target}? "
                "Si podemos acercarnos, podría comprarlo hoy mismo. Gracias."
            )
        if lang == "fr":
            return (
                f"Bonjour, je suis intéressé par {product}. "
                f"Avec le coût total, le prix est un peu élevé pour moi. "
                f"Pourriez-vous vous rapprocher de {target} ? "
                "Si oui, je pourrais commander aujourd’hui. Merci."
            )
        return (
            f"Hello, I am interested in {product}. "
            f"With shipping and possible taxes, the total cost is a bit high for me. "
            f"Could you offer a better price closer to {target}? "
            "If we can get close to that, I can order today. Thank you."
        )


ai_engine_service = AiEngineService()
