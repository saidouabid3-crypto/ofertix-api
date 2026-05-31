from __future__ import annotations

from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class VerdictCommand(str, Enum):
    BUY_NOW = "BUY_NOW"
    WAIT = "WAIT"
    AVOID = "AVOID"
    VERIFY_FIRST = "VERIFY_FIRST"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TrafficColor(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class Importance(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TrendDirection(str, Enum):
    DROP_LIKELY = "DROP_LIKELY"
    STABLE = "STABLE"
    RISE_LIKELY = "RISE_LIKELY"
    UNKNOWN = "UNKNOWN"


class LegitimacyLevel(str, Enum):
    LEGITIMATE = "LEGITIMATE"
    SUSPICIOUS = "SUSPICIOUS"
    MANIPULATIVE = "MANIPULATIVE"
    UNKNOWN = "UNKNOWN"


class CustomsHoldRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class Money(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amount: float = Field(default=0, ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper().strip()


class DarkPatternSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = Field(default="unknown", max_length=80)
    text: str = Field(default="", max_length=500)
    selector: str = Field(default="", max_length=250)
    severity: int = Field(default=20, ge=0, le=100)


class ProductExtractRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: HttpUrl
    userCountry: str = Field(default="ES", min_length=2, max_length=2)
    userCurrency: str = Field(default="EUR", min_length=3, max_length=3)
    language: str = Field(default="es", min_length=2, max_length=12)
    proxyUrl: str | None = Field(default=None, max_length=500)

    @field_validator("userCountry")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("userCurrency")
    @classmethod
    def normalize_user_currency(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("proxyUrl")
    @classmethod
    def validate_proxy(cls, value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "socks5"} or not parsed.netloc:
            raise ValueError("proxyUrl must be a valid http, https, or socks5 URL")
        return value


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="", max_length=500)
    store: str = Field(default="Unknown", max_length=120)
    storeCountry: str = Field(default="US", min_length=2, max_length=2)
    sellerLanguage: str = Field(default="en", min_length=2, max_length=12)
    currentPrice: float = Field(default=0, ge=0)
    oldPrice: float | None = Field(default=None, ge=0)
    baseCurrency: str = Field(default="EUR", min_length=3, max_length=3)
    shippingPrice: float | None = Field(default=None, ge=0)
    estimatedDeliveryDays: int | None = Field(default=None, ge=0, le=365)
    category: str = Field(default="", max_length=160)
    dimensions: str = Field(default="", max_length=300)
    weightKg: float | None = Field(default=None, ge=0, le=1000)
    specs: str = Field(default="", max_length=5000)
    rating: float | None = Field(default=None, ge=0, le=5)
    reviewCount: int | None = Field(default=None, ge=0)
    imageUrl: str | None = Field(default=None, max_length=2000)
    productUrl: str | None = Field(default=None, max_length=2000)
    darkPatternSignals: list[DarkPatternSignal] = Field(default_factory=list)

    @field_validator("baseCurrency", "storeCountry")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("sellerLanguage")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return value.strip().lower()


class UserContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    country: str = Field(default="ES", min_length=2, max_length=2)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    language: str = Field(default="es", min_length=2, max_length=12)

    @field_validator("country", "currency")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return value.strip().lower()


class AnalyzeGlobalRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product: ProductInput
    user: UserContext


class NegotiationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    productTitle: str = Field(default="", max_length=500)
    store: str = Field(default="Unknown", max_length=120)
    sellerLanguage: str = Field(default="en", min_length=2, max_length=12)
    userLanguage: str = Field(default="es", min_length=2, max_length=12)
    userCountry: str = Field(default="ES", min_length=2, max_length=2)
    currentTotalCost: Money = Field(default_factory=Money)
    targetPrice: Money = Field(default_factory=Money)
    reason: str = Field(default="", max_length=1200)

    @field_validator("userCountry")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("sellerLanguage", "userLanguage")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return value.strip().lower()


class ExtractedProductResponse(ProductInput):
    extractionConfidence: int = Field(default=0, ge=0, le=100)
    extractionNotes: list[str] = Field(default_factory=list)


class MetaCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    userLanguage: str = "es"
    userCountry: str = "ES"
    userCurrency: str = "EUR"
    store: str = "Unknown"
    storeCountry: str = "US"
    sellerLanguage: str = "en"
    confidence: int = Field(default=50, ge=0, le=100)


class VerdictCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: VerdictCommand = VerdictCommand.VERIFY_FIRST
    title: str = "Verify first"
    oneLine: str = "More data is needed before buying."
    score: int = Field(default=50, ge=0, le=100)
    riskLevel: RiskLevel = RiskLevel.MEDIUM
    color: TrafficColor = TrafficColor.YELLOW
    explanation: str = "The available information is not enough for a confident decision."


class DiscountCurrencyCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    advertisedDiscountPercent: int = Field(default=0, ge=0, le=100)
    realisticDiscountPercent: int = Field(default=0, ge=0, le=100)
    fakeDiscountRisk: int = Field(default=50, ge=0, le=100)
    storePrice: Money = Field(default_factory=Money)
    convertedProductPrice: Money = Field(default_factory=Money)
    estimatedShipping: Money = Field(default_factory=Money)
    estimatedTaxes: Money = Field(default_factory=Money)
    estimatedTaxesConfidence: int = Field(default=35, ge=0, le=100)
    totalLandedCost: Money = Field(default_factory=Money)
    realSaving: Money = Field(default_factory=Money)
    explanation: str = "The final price should be checked including shipping and taxes."


class HumanSpecItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spec: str = Field(default="", max_length=160)
    humanMeaning: str = Field(default="", max_length=500)
    importance: Importance = Importance.MEDIUM


class HumanSpecsCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = "No technical specs were provided."
    items: list[HumanSpecItem] = Field(default_factory=list)


class GlobalAlternativeCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    store: str = ""
    estimatedTotalCost: Money = Field(default_factory=Money)
    whyBetter: str = ""
    shippingAdvantage: str = ""
    url: str = ""
    confidence: int = Field(default=0, ge=0, le=100)


class DarkPatternsCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    urgencyLegitimacyScore: int = Field(default=50, ge=0, le=100)
    legitimacyLevel: LegitimacyLevel = LegitimacyLevel.UNKNOWN
    detectedSignals: list[DarkPatternSignal] = Field(default_factory=list)
    explanation: str = "No urgency manipulation could be verified."
    shopperAdvice: str = "Do not rush. Compare total price before buying."


class PriceForecastCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    trend: TrendDirection = TrendDirection.UNKNOWN
    probabilityPercent: int = Field(default=50, ge=0, le=100)
    expectedChangePercent: float = Field(default=0)
    horizonDays: int = Field(default=14, ge=1, le=30)
    explanation: str = "There is not enough history for a reliable forecast."
    bestAction: str = "Verify price history before buying."


class CustomsRiskCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    holdRisk: CustomsHoldRisk = CustomsHoldRisk.UNKNOWN
    tariffRiskPercent: int = Field(default=30, ge=0, le=100)
    estimatedExtraCost: Money = Field(default_factory=Money)
    explanation: str = "Customs and import fees depend on the product category and destination country."
    documentsAdvice: str = "Check seller invoice, return policy, and local import rules."


class NegotiationCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shouldShowButton: bool = False
    targetPrice: Money = Field(default_factory=Money)
    sellerLanguage: str = "en"
    reason: str = ""
    script: str = ""


class GlobalDealAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meta: MetaCard = Field(default_factory=MetaCard)
    verdictCard: VerdictCard = Field(default_factory=VerdictCard)
    discountCurrencyCard: DiscountCurrencyCard = Field(default_factory=DiscountCurrencyCard)
    humanSpecsCard: HumanSpecsCard = Field(default_factory=HumanSpecsCard)
    globalAlternativeCard: GlobalAlternativeCard = Field(default_factory=GlobalAlternativeCard)
    darkPatternsCard: DarkPatternsCard = Field(default_factory=DarkPatternsCard)
    priceForecastCard: PriceForecastCard = Field(default_factory=PriceForecastCard)
    customsRiskCard: CustomsRiskCard = Field(default_factory=CustomsRiskCard)
    negotiation: NegotiationCard = Field(default_factory=NegotiationCard)

    @model_validator(mode="after")
    def prevent_ui_crashes(self) -> "GlobalDealAnalysisResponse":
        if not self.humanSpecsCard.items:
            self.humanSpecsCard.items = [
                HumanSpecItem(
                    spec="Specs",
                    humanMeaning=self.humanSpecsCard.summary or "No specs available.",
                    importance=Importance.MEDIUM,
                )
            ]

        if not self.negotiation.targetPrice.currency:
            self.negotiation.targetPrice.currency = self.meta.userCurrency

        if not self.darkPatternsCard.detectedSignals:
            self.darkPatternsCard.detectedSignals = []

        return self


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    code: str = "AI_DEAL_BRAIN_ERROR"
    safeMessage: str = "Something went wrong. Please try again."
    meta: dict[str, Any] = Field(default_factory=dict)
