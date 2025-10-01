from dataclasses import dataclass
from typing import  Optional, Dict

@dataclass
class SearchCard:
    title: Optional[str]
    price_text: Optional[str]
    has_coupon: bool
    is_limited_time_deal: bool
    product_url: Optional[str]


@dataclass
class ProductDetails:
    name: Optional[str]
    seller_name: Optional[str]
    description_text: Optional[str]
    is_in_stock: Optional[bool]
    return_policy_text: Optional[str]
    images_text: Optional[str]
    details_kv: Dict[str, str]
    has_related_deals: bool
    price_current: Optional[float] = None
    price_original: Optional[float] = None
    coupon_text: Optional[str] = None
    limited_deal_text: Optional[str] = None
    discount_percent: Optional[float] = None
    discount_source: Optional[str] = None  # "coupon" | "limited_deal" | "price_compare"
