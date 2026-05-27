from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class StoreRecognitionResult:
    store_id: str | None
    store_name: str | None
    domain: str | None
    country_code: str | None
    currency: str | None
    confidence: float
    reason: str


class StoreRecognitionService:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db

    def recognize(self, product: dict[str, Any]) -> StoreRecognitionResult:
        text = self._blob(product)
        domain = self._extract_domain(product)
        cfg = self._match_store_config(text=text, domain=domain)
        if cfg:
            return StoreRecognitionResult(
                store_id=str(cfg.get('storeId') or cfg.get('id') or cfg.get('slug') or ''),
                store_name=str(cfg.get('name') or cfg.get('storeName') or ''),
                domain=domain,
                country_code=self._clean_country(cfg.get('countryCode')),
                currency=self._clean_currency(cfg.get('currency')),
                confidence=0.96,
                reason='store_config_match',
            )
        fallback = self._fallback_domain(domain=domain, text=text)
        if fallback:
            country, store_name, reason = fallback
            return StoreRecognitionResult(None, store_name, domain, country, None, 0.88, reason)
        explicit_store = str(product.get('store') or product.get('source') or product.get('provider') or '').strip()
        return StoreRecognitionResult(None, explicit_store or None, domain, None, self._clean_currency(product.get('currency')), 0.0, 'unknown_store_requires_review')

    def _match_store_config(self, text: str, domain: str | None) -> dict[str, Any] | None:
        if self.db is None:
            return None
        try:
            docs = self.db.collection('store_configs').where('enabled', '==', True).limit(300).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                domains = data.get('domains') or []
                aliases = data.get('aliases') or []
                if isinstance(domains, str):
                    domains = [domains]
                if isinstance(aliases, str):
                    aliases = [aliases]
                for item in domains:
                    clean = str(item or '').lower().strip().replace('www.', '')
                    if clean and domain and clean in domain:
                        data.setdefault('storeId', doc.id)
                        return data
                for item in aliases:
                    clean = str(item or '').lower().strip()
                    if clean and clean in text:
                        data.setdefault('storeId', doc.id)
                        return data
        except Exception:
            return None
        return None

    @staticmethod
    def _blob(product: dict[str, Any]) -> str:
        keys = ['source', 'store', 'storeName', 'provider', 'merchant', 'seller', 'url', 'productUrl', 'affiliateUrl', 'link', 'domain', 'marketplace', 'title', 'name', 'description']
        return ' '.join(str(product.get(k) or '').lower() for k in keys)

    @staticmethod
    def _extract_domain(product: dict[str, Any]) -> str | None:
        for key in ['domain', 'url', 'productUrl', 'affiliateUrl', 'link']:
            raw = str(product.get(key) or '').strip()
            if not raw:
                continue
            if '://' not in raw:
                raw = 'https://' + raw
            try:
                host = urlparse(raw).netloc.lower().replace('www.', '')
                if host:
                    return host
            except Exception:
                pass
        return None

    @staticmethod
    def _clean_country(value: Any) -> str | None:
        raw = str(value or '').lower().strip()
        aliases = {'spain':'es','españa':'es','espana':'es','morocco':'ma','maroc':'ma','algeria':'dz','algerie':'dz','algérie':'dz','france':'fr','germany':'de','italy':'it','portugal':'pt','usa':'us','united states':'us','uk':'uk','gb':'uk','united kingdom':'uk','canada':'ca','egypt':'eg','saudi arabia':'sa','uae':'ae','emirates':'ae','mexico':'mx','méxico':'mx'}
        raw = aliases.get(raw, raw)
        return raw if len(raw) == 2 and raw.isalpha() else None

    @staticmethod
    def _clean_currency(value: Any) -> str | None:
        raw = str(value or '').upper().strip()
        return raw if len(raw) == 3 and raw.isalpha() else None

    @staticmethod
    def _fallback_domain(domain: str | None, text: str) -> tuple[str, str, str] | None:
        full = f'{domain or ""} {text}'.lower()
        rules = [
            ('amazon.es','es','Amazon Spain'),('pccomponentes','es','PCComponentes'),('mediamarkt.es','es','MediaMarkt Spain'),('carrefour.es','es','Carrefour Spain'),('miravia','es','Miravia'),('elcorteingles','es','El Corte Inglés'),
            ('amazon.fr','fr','Amazon France'),('cdiscount','fr','Cdiscount'),('fnac.com','fr','Fnac France'),
            ('jumia.ma','ma','Jumia Morocco'),('jumia.dz','dz','Jumia Algeria'),('ouedkniss','dz','Ouedkniss'),
            ('amazon.de','de','Amazon Germany'),('amazon.it','it','Amazon Italy'),('amazon.co.uk','uk','Amazon UK'),('amazon.com.mx','mx','Amazon Mexico'),('amazon.ca','ca','Amazon Canada'),('amazon.com','us','Amazon US'),
            ('amazon.ae','ae','Amazon UAE'),('amazon.sa','sa','Amazon Saudi Arabia'),('amazon.eg','eg','Amazon Egypt'),('noon.com/uae','ae','Noon UAE'),('noon.com/saudi','sa','Noon Saudi Arabia')]
        for needle, country, name in rules:
            if needle in full:
                return country, name, f'domain_hint:{needle}'
        # Cross-border marketplaces must stay review unless shipping is explicit.
        if 'aliexpress' in full or 'ali express' in full:
            return None
        return None
