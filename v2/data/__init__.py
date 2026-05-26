"""v2 data pipeline — data provider protocol, FD client, and response models."""

from v2.data.client import FDClient
from v2.data.composite_client import CompositeClient, make_hybrid_client
from v2.data.eodhd_client import EODHDClient
from v2.data.factory import (
    get_default_provider,
    get_provider_factory,
    make_data_client,
    recommend_max_workers,
)
from v2.data.finnhub_client import FinnhubClient
from v2.data.models import (
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsData,
    EarningsRecord,
    Filing,
    FinancialMetrics,
    InsiderTrade,
    Price,
)
from v2.data.protocol import DataClient

__all__ = [
    "CompanyFacts",
    "CompanyNews",
    "CompositeClient",
    "DataClient",
    "Earnings",
    "EarningsData",
    "EarningsRecord",
    "EODHDClient",
    "FDClient",
    "Filing",
    "FinnhubClient",
    "make_hybrid_client",
    "FinancialMetrics",
    "InsiderTrade",
    "Price",
    "get_default_provider",
    "get_provider_factory",
    "make_data_client",
    "recommend_max_workers",
]
