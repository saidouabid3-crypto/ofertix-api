from fastapi import APIRouter, Query
from core.market_config import SUPPORTED_MARKETS, normalize_market

router = APIRouter(prefix='/market', tags=['market'])

@router.get('/countries')
def countries():
    return {'countries': [{'code': code, **data} for code, data in SUPPORTED_MARKETS.items()]}

@router.get('/resolve')
def resolve(country: str = Query(default='es')):
    code = normalize_market(country)
    return {'countryCode': code, **SUPPORTED_MARKETS[code]}
