"""Current orchestrator adapter capability contracts."""

from crawlers.marts.costco.plugin import CostcoPlugin
from crawlers.marts.emart.plugin import EmartPlugin
from crawlers.marts.homeplus.plugin import HomeplusPlugin
from crawlers.marts.lottemart.plugin import LottemartPlugin


def test_core_mart_adapters_do_not_claim_targeted_search():
    for plugin in (EmartPlugin(), HomeplusPlugin(), LottemartPlugin(), CostcoPlugin()):
        assert plugin.supports_targeted_search("우유") is False
