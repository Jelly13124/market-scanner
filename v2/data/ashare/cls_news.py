"""财联社 (Caixinglian / CLS) per-stock news scraper.

CLS exposes a depth-feed endpoint at www.cls.cn/v3/cms that returns
per-stock news in JSON. No auth, no API key. Per the spec, A-share
news is capped at 50 articles per fetch (vs 200 for US) to keep SOP
section prompts under token budget.
"""

from __future__ import annotations

from datetime import datetime

import requests

from v2.data.models import CompanyNews

_URL = "https://www.cls.cn/v3/cms/article/depth-list/v1?app=CailianpressWeb"


def _code_only(canonical: str) -> str:
    return canonical.split('.', 1)[0]


def fetch_stock_news(
    canonical_ticker: str,
    end_date: str,
    *,
    start_date: str | None = None,
    limit: int = 50,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[CompanyNews]:
    sess = session or requests.Session()
    params = {
        "secu_code": f"{canonical_ticker.split('.', 1)[1].lower()}{_code_only(canonical_ticker)}",
        "rn": min(limit, 50),
    }
    resp = sess.get(_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    rows = ((payload.get("data") or {}).get("depth_list")) or []
    if not rows:
        return []

    end_ts = datetime.fromisoformat(end_date).timestamp()
    start_ts = (
        datetime.fromisoformat(start_date).timestamp() if start_date else 0
    )

    out: list[CompanyNews] = []
    for row in rows[:limit]:
        ctime = row.get("ctime") or 0
        if not (start_ts <= ctime <= end_ts + 86400):  # +1d slack
            continue
        out.append(CompanyNews(
            ticker=canonical_ticker,
            title=row.get("title", ""),
            source="财联社",
            date=datetime.fromtimestamp(ctime).strftime("%Y-%m-%d"),
            url=row.get("share_url", ""),
            sentiment=None,        # CLS doesn't ship sentiment
            sentiment_score=None,
        ))
    return out
