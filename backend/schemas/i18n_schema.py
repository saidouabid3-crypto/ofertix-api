from typing import List
from pydantic import BaseModel


class CountryOut(BaseModel):
    code: str
    name: str
    currency: str
    language: str


class LanguageOut(BaseModel):
    code: str
    name: str
    native_name: str


class CountriesResponse(BaseModel):
    items: List[CountryOut]


class LanguagesResponse(BaseModel):
    items: List[LanguageOut]
