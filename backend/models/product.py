from pydantic import BaseModel


class Product(BaseModel):
    name: str
    description: str = ""
    image: str = ""

    oldPrice: float = 0
    newPrice: float = 0
    discount: int = 0

    store: str = ""
    category: str = ""

    affiliateUrl: str = ""

    isHot: bool = False
    isOnline: bool = True

    country: str = "global"

    lat: float = 0
    lng: float = 0

    views: int = 0
    clicks: int = 0
    sales: int = 0

    featured: bool = False
    sponsored: bool = False