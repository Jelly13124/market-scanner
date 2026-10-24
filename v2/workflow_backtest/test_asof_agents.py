import src.tools.api as api_mod
import v2.data.factory as factory_mod
from v2.workflow_backtest.asof_agents import asof_agent_context


class _FakeDispatcher:
    def __init__(self):
        self.asof = None

    def set_asof(self, d):
        self.asof = d


def test_context_swaps_and_restores():
    orig_cache = api_mod._v2_client_cache
    orig_factory = factory_mod.get_provider_factory
    disp = _FakeDispatcher()
    with asof_agent_context(disp, "2025-03-03"):
        assert disp.asof == "2025-03-03"
        assert api_mod._v2_client_cache is disp
        assert factory_mod.get_provider_factory()() is disp   # factory returns a factory→dispatcher
    assert api_mod._v2_client_cache is orig_cache
    assert factory_mod.get_provider_factory is orig_factory
