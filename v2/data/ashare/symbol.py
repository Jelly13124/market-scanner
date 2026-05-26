"""A-share symbol detection + canonical-form normalization.

Canonical form: '<6-digit-code>.<SH|SZ|BJ>'
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"^[0-9]{6}$")
_WITH_SUFFIX = re.compile(r"^([0-9]{6})\.(SH|SZ|BJ)$", re.IGNORECASE)
_WITH_PREFIX = re.compile(r"^(SH|SZ|BJ)\.?([0-9]{6})$", re.IGNORECASE)


def is_ashare(ticker: str) -> bool:
    """Return True iff ticker matches any accepted A-share form."""
    if not ticker:
        return False
    t = ticker.strip()
    return bool(
        _DIGITS.match(t)
        or _WITH_SUFFIX.match(t)
        or _WITH_PREFIX.match(t)
    )


def infer_exchange(code: str) -> str:
    """From a 6-digit code, infer the exchange. Returns 'SH' | 'SZ' | 'BJ'.

    Prefix rules (per exchange's listed code allocation):
      SH: 6xxxxx (A), 9xxxxx (B-share)
      SZ: 0xxxxx (A), 3xxxxx (ChiNext), 2xxxxx (B-share)
      BJ: 4xxxxx, 8xxxxx, 9[2-9]xxxx
    """
    if not _DIGITS.match(code):
        raise ValueError(f"not a 6-digit code: {code!r}")
    p = code[0]
    if p == "6" or p == "9":
        # 92-99 belongs to BJ; 90-91 belongs to SH B-share
        if p == "9" and code[1] in ("2", "3", "4", "5", "6", "7", "8", "9"):
            return "BJ"
        return "SH"
    if p in ("0", "3", "2"):
        return "SZ"
    if p in ("4", "8"):
        return "BJ"
    raise ValueError(f"unrecognized A-share code prefix: {code!r}")


def normalize(ticker: str) -> str:
    """Convert any accepted A-share form to canonical '<code>.<exchange>'.

    Raises ValueError on non-A-share input.
    """
    if not is_ashare(ticker):
        raise ValueError(f"not an A-share ticker: {ticker!r}")
    t = ticker.strip()
    if m := _WITH_SUFFIX.match(t):
        return f"{m.group(1)}.{m.group(2).upper()}"
    if m := _WITH_PREFIX.match(t):
        return f"{m.group(2)}.{m.group(1).upper()}"
    # bare 6 digits - infer
    return f"{t}.{infer_exchange(t)}"
