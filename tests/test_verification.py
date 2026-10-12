from blackout.config import load_scenario
from blackout.verification import physical_links, run_exhaustive_rerouting_check


def test_presentation_physical_link_inventory_is_stable() -> None:
    scenario = load_scenario("configs/presentation.yaml")

    links = physical_links(scenario)

    assert len(links) == 21
    assert ("A", "B") in links
    assert ("I", "L") in links
    assert ("K", "L") not in links


def test_every_endpoint_pair_survives_every_single_link_failure() -> None:
    report = run_exhaustive_rerouting_check(
        load_scenario("configs/presentation.yaml")
    )

    assert report["total_cases"] == 3036
    assert report["passed_cases"] == 3036
    assert report["failed_cases"] == 0
    assert report["failures"] == []
