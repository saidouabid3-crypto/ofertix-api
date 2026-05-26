class AIBrainService:
    """Lightweight AI brain.

    This service is intentionally cheap and fast. It gives rules-based decisions first,
    and can later be upgraded to call Groq/OpenAI only on explicit Ask AI actions.
    """

    def analyze(self, payload):
        query = payload.query.strip().lower()
        current = payload.current_price
        old = payload.old_price
        discount = 0
        if current and old and old > current:
            discount = int(((old - current) / old) * 100)

        risk = 'low'
        confidence = 70
        verdict = 'neutral'
        summary = 'Puedo ayudarte a comparar precio, tienda, cupón y riesgo antes de comprar.'

        if discount >= 40:
            verdict = 'strong_deal'
            confidence = 86
            summary = f'Oferta fuerte: descuento aproximado de {discount}%.'
        elif discount >= 15:
            verdict = 'good_deal'
            confidence = 76
            summary = f'Oferta interesante: descuento aproximado de {discount}%.'
        elif current and old and old <= current:
            verdict = 'not_recommended'
            risk = 'medium'
            confidence = 72
            summary = 'El precio antiguo no parece mejorar el precio actual. Revisa antes de comprar.'
        elif any(word in query for word in ['fake', 'falso', 'engaño', 'estafa']):
            verdict = 'check_discount'
            risk = 'medium'
            confidence = 78
            summary = 'Conviene revisar historial de precio y votos Hot/Cold antes de comprar.'
        elif any(word in query for word in ['coupon', 'cupón', 'cupon']):
            verdict = 'coupon_help'
            confidence = 75
            summary = 'Busca cupones verificados y revisa fecha de caducidad y votos de usuarios.'

        suggestions = [
            'Comparar con otras tiendas',
            'Revisar Hot/Cold de la comunidad',
            'Buscar cupón activo',
            'Añadir a Watchlist si no urge',
        ]

        return {
            'intent': self._detect_intent(query),
            'verdict': verdict,
            'confidence': confidence,
            'summary': summary,
            'suggestions': suggestions,
            'risk_level': risk,
            'lightweight': True,
        }

    def _detect_intent(self, query: str) -> str:
        if any(x in query for x in ['coupon', 'cupón', 'cupon']):
            return 'coupon_search'
        if any(x in query for x in ['fake', 'falso', 'engaño', 'estafa']):
            return 'fake_discount_check'
        if any(x in query for x in ['compare', 'comparar', 'mejor']):
            return 'compare_products'
        if any(x in query for x in ['reel', 'title', 'título', 'descripcion']):
            return 'reel_assistant'
        return 'shopping_advice'


ai_brain_service = AIBrainService()
