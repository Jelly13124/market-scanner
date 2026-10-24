"""Phase 8: 申万一级 (SW1) sector name -> index code mapping."""
from v2.data.ashare.sw_sector_map import sw1_index_code, SW1_SECTORS


def test_maps_known_sector():
    # 食品饮料 -> SW1 food & beverage index
    assert sw1_index_code("食品饮料") == "801120.SH"


def test_returns_none_for_unknown():
    assert sw1_index_code("not a sector") is None


def test_registry_has_31_sectors():
    # SW1 has 31 first-level sectors as of 2024
    assert len(SW1_SECTORS) == 31
