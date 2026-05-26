import os
from datetime import datetime

from repositories.ai_brain_repository import ai_brain_repository
from services.ai_service import ai_service
from services.deal_score_service import DealScoreService
from services.fake_discount_service import FakeDiscountService


class AIBrainService:
    async def analyze(self, payload, current_user: dict):
        base = self._rules_analysis(payload)
        groq_text = await self._groq_analysis(payload, base)
        if groq_text:
            base['summary'] = groq_text
            base['model_used'] = os.getenv('GROQ_MODEL', 'groq')
        saved = ai_brain_repository.save(
            user_id=current_user['uid'],
            payload=payload.model_dump(),
            result=base,
        )
        return saved

    def history(self, current_user: dict, limit: int = 30):
        return {'items': ai_brain_repository.history(user_id=current_user['uid'], limit=limit)}

    def _rules_analysis(self, payload) -> dict:
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
        risk = 'low'
        verdict = 'compare'
        best_action = 'compare_more'
        price_signal = 'unknown'
        confidence = 72
        fair_price = None
        reasons = []

        if old and current:
            fair_price = round((old + current) / 2, 2) if old > current else current
            if old <= current:
                verdict = 'bad_deal'
                risk = 'medium'
                price_signal = 'price_not_lower'
                best_action = 'wait'
                confidence = 80
                reasons.append('El precio antiguo no mejora el precio actual.')
            elif discount >= 35:
                verdict = 'buy_now'
                price_signal = 'strong_drop'
                best_action = 'buy_if_needed'
                confidence = 88
                reasons.append(f'Descuento fuerte aproximado de {discount}%.')
            elif discount >= 15:
                verdict = 'good_deal'
                price_signal = 'fair_drop'
                best_action = 'compare_then_buy'
                confidence = 78
                reasons.append(f'Descuento interesante aproximado de {discount}%.')
            else:
                verdict = 'wait'
                price_signal = 'small_drop'
                best_action = 'add_to_watchlist'
                reasons.append('La rebaja existe, pero no parece agresiva.')

        if any(word in query for word in ['fake', 'falso', 'engaño', 'estafa']):
            risk = 'medium' if risk == 'low' else risk
            verdict = 'check_discount'
            best_action = 'verify_history'
            reasons.append('El usuario pidió revisar posible descuento falso.')

        if payload.specs:
            reasons.append('Specs detectadas: se preparó explicación simple para compra informada.')

        suggestions = [
            'Comparar precio con 2 o 3 tiendas antes de pagar',
            'Revisar Hot/Cold y comentarios de la comunidad',
            'Activar alerta si el precio no es urgente',
            'Comprobar vendedor, garantía y devolución',
        ]
        alternatives = self._alternatives(payload)
        specs_explained = self._explain_specs(payload.specs or '')
        summary = self._summary(verdict, discount, payload.store, current, payload.currency)

        return {
            'intent': self._detect_intent(query),
            'verdict': verdict,
            'score': int(max(0, min(100, score))),
            'confidence': int(confidence),
            'summary': summary,
            'suggestions': suggestions,
            'risk_level': risk,
            'fake_discount_risk': fake_risk,
            'price_signal': price_signal,
            'best_action': best_action,
            'savings_estimate': round(savings, 2),
            'fair_price_estimate': fair_price,
            'alternatives': alternatives,
            'specs_explained': specs_explained,
            'reasons': reasons,
            'model_used': 'rules_plus_groq_optional',
            'created_at': datetime.utcnow().isoformat(),
        }

    async def _groq_analysis(self, payload, base: dict) -> str:
        if not os.getenv('GROQ_API_KEY'):
            return ''
        prompt = (
            'Actúa como comprador experto en España. Resume en máximo 70 palabras si conviene comprar. '
            'No inventes datos. Usa tono claro y directo. Datos: '
            f'query={payload.query}; title={payload.title}; store={payload.store}; price={payload.current_price}; old={payload.old_price}; verdict={base.get("verdict")}; risk={base.get("risk_level")}'
        )
        try:
            result = await ai_service.analyze_query(query=prompt, country_code=payload.country, currency=payload.currency, language=payload.language)
            answer = result.get('answer') or result.get('summary') or ''
            return str(answer).strip()[:700]
        except Exception:
            return ''

    def _detect_intent(self, query: str) -> str:
        if any(x in query for x in ['coupon', 'cupón', 'cupon']):
            return 'coupon_search'
        if any(x in query for x in ['fake', 'falso', 'engaño', 'estafa']):
            return 'fake_discount_check'
        if any(x in query for x in ['compare', 'comparar', 'mejor']):
            return 'compare_products'
        if any(x in query for x in ['spec', 'specs', 'característica', 'ram', 'procesador']):
            return 'specs_translator'
        return 'shopping_advice'

    def _summary(self, verdict: str, discount: int, store: str | None, current: float | None, currency: str) -> str:
        place = f' en {store}' if store else ''
        price = f' por {current:.2f} {currency}' if current else ''
        if verdict == 'buy_now':
            return f'Compra recomendable{place}{price}: el descuento aproximado es fuerte ({discount}%).'
        if verdict == 'good_deal':
            return f'Buena oferta{place}{price}, pero compara una tienda más antes de pagar.'
        if verdict == 'bad_deal':
            return 'No parece una oferta real: el precio anterior no mejora el actual.'
        if verdict == 'wait':
            return 'Mejor esperar o activar alerta: la rebaja no parece suficientemente fuerte.'
        return 'Analiza precio, tienda, garantía y opiniones antes de comprar.'

    def _alternatives(self, payload) -> list[str]:
        title = (payload.title or payload.query or '').strip()
        if not title:
            return ['Buscar alternativa reacondicionada', 'Comparar con marca equivalente', 'Esperar una rebaja verificada']
        return [
            f'Buscar {title} reacondicionado con garantía',
            f'Comparar {title} en Amazon, MediaMarkt y PcComponentes',
            f'Crear alerta de precio para {title}',
        ]

    def _explain_specs(self, specs: str) -> list[str]:
        if not specs.strip():
            return []
        parts = [x.strip() for x in specs.replace('\n', ',').split(',') if x.strip()]
        explanations = []
        for part in parts[:5]:
            lower = part.lower()
            if 'ram' in lower:
                explanations.append(f'{part}: afecta a fluidez y multitarea.')
            elif 'gb' in lower or 'tb' in lower:
                explanations.append(f'{part}: revisa si el almacenamiento te llega para 2-3 años.')
            elif 'hz' in lower:
                explanations.append(f'{part}: pantalla más fluida, útil para gaming y scroll.')
            else:
                explanations.append(f'{part}: compáralo con tu uso real antes de pagar extra.')
        return explanations


ai_brain_service = AIBrainService()
