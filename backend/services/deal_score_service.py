class DealScoreService:
    @staticmethod
    def calculate_score(
        current_price: float,
        old_price: float | None,
        views: int = 0,
        likes: int = 0,
        clicks: int = 0,
        reports: int = 0,
    ) -> int:
        score = 50

        if old_price and old_price > current_price:
            discount = ((old_price - current_price) / old_price) * 100

            if discount >= 50:
                score += 30
            elif discount >= 30:
                score += 22
            elif discount >= 20:
                score += 15
            elif discount >= 10:
                score += 8

        if clicks >= 20:
            score += 10
        elif clicks >= 5:
            score += 5

        if likes >= 20:
            score += 8
        elif likes >= 5:
            score += 4

        if reports > 0:
            score -= reports * 10

        return max(0, min(100, int(score)))

    @staticmethod
    def ai_verdict(score: int) -> str:
        if score >= 85:
            return "Compra inteligente"
        if score >= 70:
            return "Buena oferta"
        if score >= 50:
            return "Oferta normal"
        return "Mejor esperar"