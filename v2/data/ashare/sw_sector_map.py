"""申万一级 (SW1) sector index codes — used as A-share sector ETF
benchmarks in the SOP analyze pipeline.

A-share doesn't have liquid sector ETFs in the SPDR sense. SW1 indices
are the standard reference — published by 申银万国 since 1999. 31
first-level sectors as of 2024 reclassification.

We map Eastmoney's SECTOR_NAME strings (returned by F10 JBZL) to SW1
index ticker codes. Loaders can then call get_prices() on the index
ticker just like SPY for US flow.
"""

from __future__ import annotations

SW1_SECTORS: dict[str, str] = {
    "农林牧渔": "801010.SH",
    "采掘": "801020.SH",
    "化工": "801030.SH",
    "钢铁": "801040.SH",
    "有色金属": "801050.SH",
    "电子": "801080.SH",
    "家用电器": "801110.SH",
    "食品饮料": "801120.SH",
    "纺织服装": "801130.SH",
    "轻工制造": "801140.SH",
    "医药生物": "801150.SH",
    "公用事业": "801160.SH",
    "交通运输": "801170.SH",
    "房地产": "801180.SH",
    "商业贸易": "801200.SH",
    "休闲服务": "801210.SH",
    "综合": "801230.SH",
    "建筑材料": "801710.SH",
    "建筑装饰": "801720.SH",
    "电气设备": "801730.SH",
    "国防军工": "801740.SH",
    "计算机": "801750.SH",
    "传媒": "801760.SH",
    "通信": "801770.SH",
    "银行": "801780.SH",
    "非银金融": "801790.SH",
    "汽车": "801880.SH",
    "机械设备": "801890.SH",
    "煤炭": "801950.SH",
    "石油石化": "801960.SH",
    "环保": "801970.SH",
}


def sw1_index_code(sector_name: str) -> str | None:
    """Map an Eastmoney F10 SECTOR_NAME to a SW1 index code.
    Returns None for unknown sector. Case-sensitive (Chinese chars)."""
    return SW1_SECTORS.get(sector_name.strip()) if sector_name else None
