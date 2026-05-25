class FakeDiscountService:
    @staticmethod
    def detect_risk(current_price: float, old_price: float | None) -> str:
        if not old_price or old_price <= current_price:
            return "unknown"

        discount = ((old_price - current_price) / old_price) * 100

        if discount >= 80:
            return "high"
        if discount >= 50:
            return "medium"
        return "low"