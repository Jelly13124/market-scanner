"""A-share market cap via Tencent's qt.gtimg.cn snapshot endpoint.

Returns total market cap in RMB (not 万元 or 亿元). end_date arg is
accepted for protocol parity but Tencent's endpoint serves real-time
only -- caller gets 'current' market cap, not historical-at-date.
For SOP analyze on the latest scan_date this is fine.

(Module name kept as eastmoney_market_cap.py for plan / import-path
parity; data source is actually qt.gtimg.cn, which is Tencent's free
quote endpoint commonly grouped with Eastmoney-family scrapers in
A-share toolkits.)
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_URL = "https://qt.gtimg.cn/q={pre_code}"


def _pre_code(canonical: str) -> str:
    code, exch = canonical.split('.', 1)
    return f"{exch.lower()}{code}"


def fetch_market_cap(
    canonical_ticker: str,
    end_date: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> float | None:
    sess = session or requests.Session()
    resp = sess.get(
        _URL.format(pre_code=_pre_code(canonical_ticker)), timeout=timeout,
    )
    resp.raise_for_status()
    # Format: v_sh600519="1~name~code~...~CAP_YI~..."
    txt = resp.text
    if '="' not in txt:
        return None
    body = txt.split('="', 1)[1].rstrip('";\n ')
    fields = body.split('~')
    # Field 45 (0-indexed) is total market cap in 亿元. Index can drift
    # between Tencent revisions -- check len() and validate numeric.
    if len(fields) < 46:
        return None
    try:
        cap_yi = float(fields[45])
    except ValueError:
        return None
    if cap_yi <= 0:
        return None
    return cap_yi * 100_000_000  # 1 亿 = 100,000,000
