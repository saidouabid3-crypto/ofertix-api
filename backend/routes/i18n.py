from fastapi import APIRouter

from schemas.i18n_schema import CountriesResponse, LanguagesResponse

router = APIRouter(prefix='/i18n', tags=['Countries Languages Currencies'])

COUNTRIES = [
    {'code': 'ES', 'name': 'Spain', 'currency': 'EUR', 'language': 'es'},
    {'code': 'FR', 'name': 'France', 'currency': 'EUR', 'language': 'fr'},
    {'code': 'DE', 'name': 'Germany', 'currency': 'EUR', 'language': 'de'},
    {'code': 'IT', 'name': 'Italy', 'currency': 'EUR', 'language': 'it'},
    {'code': 'PT', 'name': 'Portugal', 'currency': 'EUR', 'language': 'pt'},
    {'code': 'NL', 'name': 'Netherlands', 'currency': 'EUR', 'language': 'nl'},
    {'code': 'BE', 'name': 'Belgium', 'currency': 'EUR', 'language': 'fr'},
    {'code': 'GB', 'name': 'United Kingdom', 'currency': 'GBP', 'language': 'en'},
    {'code': 'US', 'name': 'United States', 'currency': 'USD', 'language': 'en'},
    {'code': 'CA', 'name': 'Canada', 'currency': 'CAD', 'language': 'en'},
    {'code': 'MA', 'name': 'Morocco', 'currency': 'MAD', 'language': 'ar'},
    {'code': 'DZ', 'name': 'Algeria', 'currency': 'DZD', 'language': 'ar'},
    {'code': 'TN', 'name': 'Tunisia', 'currency': 'TND', 'language': 'ar'},
    {'code': 'SA', 'name': 'Saudi Arabia', 'currency': 'SAR', 'language': 'ar'},
    {'code': 'AE', 'name': 'United Arab Emirates', 'currency': 'AED', 'language': 'ar'},
    {'code': 'QA', 'name': 'Qatar', 'currency': 'QAR', 'language': 'ar'},
    {'code': 'KW', 'name': 'Kuwait', 'currency': 'KWD', 'language': 'ar'},
    {'code': 'EG', 'name': 'Egypt', 'currency': 'EGP', 'language': 'ar'},
    {'code': 'TR', 'name': 'Turkey', 'currency': 'TRY', 'language': 'tr'},
    {'code': 'BR', 'name': 'Brazil', 'currency': 'BRL', 'language': 'pt'},
    {'code': 'MX', 'name': 'Mexico', 'currency': 'MXN', 'language': 'es'},
]

LANGUAGES = [
    {'code': 'es', 'name': 'Spanish', 'native_name': 'Español'},
    {'code': 'en', 'name': 'English', 'native_name': 'English'},
    {'code': 'fr', 'name': 'French', 'native_name': 'Français'},
    {'code': 'ar', 'name': 'Arabic', 'native_name': 'العربية'},
    {'code': 'ary', 'name': 'Moroccan Darija', 'native_name': 'الدارجة المغربية'},
    {'code': 'de', 'name': 'German', 'native_name': 'Deutsch'},
    {'code': 'it', 'name': 'Italian', 'native_name': 'Italiano'},
    {'code': 'pt', 'name': 'Portuguese', 'native_name': 'Português'},
    {'code': 'nl', 'name': 'Dutch', 'native_name': 'Nederlands'},
    {'code': 'tr', 'name': 'Turkish', 'native_name': 'Türkçe'},
]


@router.get('/countries', response_model=CountriesResponse)
async def countries():
    return {'items': COUNTRIES}


@router.get('/languages', response_model=LanguagesResponse)
async def languages():
    return {'items': LANGUAGES}
