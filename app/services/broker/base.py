from dataclasses import dataclass
from typing import Literal, Protocol

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "SL", "SL-M"]
Product = Literal["MIS", "NRML", "CNC"]


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    qty: int
    order_type: OrderType = "MARKET"
    product: Product = "MIS"
    price: float | None = None
    trigger_price: float | None = None
    tag: str | None = None


@dataclass
class OrderResult:
    order_id: str
    status: str  # COMPLETE / OPEN / REJECTED
    avg_price: float
    filled_qty: int
    message: str = ""


class Broker(Protocol):
    mode: str

    def place_order(self, req: OrderRequest) -> OrderResult: ...

    def cancel_order(self, order_id: str) -> bool: ...

    def get_quote(self, symbol: str) -> float: ...
