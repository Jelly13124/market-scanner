from __future__ import annotations
from app.backend.models.screener_preset_schemas import (
    PresetCreate, PresetPatch, PresetOut,
)


def test_create_defaults():
    c = PresetCreate(name="a", filters={"pe_max": 20})
    assert c.sort_by == "market_cap" and c.market is None


def test_patch_all_optional():
    p = PresetPatch()
    assert p.model_dump(exclude_unset=True) == {}


def test_out_from_attrs():
    class Row:
        id = 1; name = "a"; market = "US"; filters_json = {"pe_max": 20}
        sort_by = "market_cap"; sort_dir = "desc"; schedule_enabled = True
        cron_expr = "5 22 * * *"
        notify_channels = ["email"]; last_run_at = None; last_match_count = 3
    o = PresetOut.model_validate(Row())
    assert o.id == 1 and o.filters == {"pe_max": 20} and o.last_match_count == 3
