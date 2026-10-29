"""Manual USD paper trading; never places an order with a real broker."""
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, Field, field_validator

Price = Annotated[Decimal, Field(gt=0, le=1_000_000_000, decimal_places=6, allow_inf_nan=False)]
Ticker = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,19}$")]


class PaperAccountCreate(BaseModel):
    initial_cash: Decimal = Field(default=Decimal("100000"), ge=1, le=1_000_000_000, decimal_places=6, allow_inf_nan=False)


class PaperOrderCreate(BaseModel):
    ticker: Ticker
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, le=1_000_000, decimal_places=6, allow_inf_nan=False)
    price: Price

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class PaperMarkCreate(BaseModel):
    ticker: Ticker
    price: Price

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value):
        return value.strip().upper() if isinstance(value, str) else value
