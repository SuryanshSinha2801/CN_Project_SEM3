"""Exhaustive deterministic verification for the presentation network."""

from __future__ import annotations

from itertools import combinations, permutations
from typing import Any

from blackout.config import MessageConfig, ScenarioConfig
from blackout.events import EventType
from blackout.models import MessageState
from blackout.simulation import build_simulation
from blackout.simulation.topology import Link, canonical_link


def physical_links(scenario: ScenarioConfig) -> tuple[Link, ...]:
    """Return every initial bidirectional radio link in a scenario."""

    links: list[Link] = []
    nodes = {node.node_id: node for node in scenario.nodes}
    for node_a_id, node_b_id in combinations(sorted(nodes), 2):
        node_a = nodes[node_a_id]
        node_b = nodes[node_b_id]
        distance = (
            (node_a.position.x - node_b.position.x) ** 2
            + (node_a.position.y - node_b.position.y) ** 2
        ) ** 0.5
        if distance <= min(node_a.communication_range, node_b.communication_range):
            links.append((node_a_id, node_b_id))
    return tuple(links)


def run_exhaustive_rerouting_check(scenario: ScenarioConfig) -> dict[str, Any]:
    """Test every ordered endpoint pair against every single physical-link failure."""

    node_ids = tuple(sorted(node.node_id for node in scenario.nodes))
    links = physical_links(scenario)
    failures: list[dict[str, Any]] = []
    total_cases = 0
    delivered_cases = 0

    def record_case(
        source: str,
        destination: str,
        mode: str,
        failed_link: Link | None,
    ) -> None:
        nonlocal delivered_cases, total_cases
        total_cases += 1
        message_id = "exhaustive-message"
        message_config = MessageConfig(
            message_id=message_id,
            source=source,
            destination=destination,
            size_bytes=1024,
            creation_time=0,
            ttl_seconds=scenario.duration_seconds,
            content="exhaustive rerouting verification",
        )
        case_scenario = scenario.model_copy(
            update={
                "name": f"exhaustive-{source}-{destination}-{mode}",
                "messages": (message_config,),
                "forced_link_failures": (),
            }
        )
        simulation = build_simulation(case_scenario)
        selected_link = failed_link
        if mode == "selected":
            assert selected_link is not None
            selected_link = simulation.break_link(*selected_link)
        elif mode == "random":
            simulation.run(until=0)
            selected_link = simulation.break_random_active_link(duration_seconds=8)
        simulation.run()

        message = simulation.messages[(message_id, "original")]
        route = [(hop.from_node, hop.to_node) for hop in message.hop_history]
        problems: list[str] = []
        if message.state is not MessageState.DELIVERED:
            problems.append(f"message ended as {message.state.value}")
        if mode == "selected":
            assert selected_link is not None
            if selected_link not in simulation.topology.blocked_links:
                problems.append("selected link did not remain blocked")
            if any(canonical_link(*hop) == selected_link for hop in route):
                problems.append("route traversed the selected failed link")
            if any(
                event.event_type is EventType.LINK_RESTORED
                and event.payload.get("manual_failure")
                for event in simulation.engine.event_log
            ):
                problems.append("selected link emitted a restoration event")
        if problems:
            failures.append(
                {
                    "source": source,
                    "destination": destination,
                    "mode": mode,
                    "failed_link": selected_link,
                    "route": route,
                    "problems": problems,
                }
            )
        else:
            delivered_cases += 1

    for source, destination in permutations(node_ids, 2):
        record_case(source, destination, "none", None)
        record_case(source, destination, "random", None)
        for link in links:
            record_case(source, destination, "selected", link)

    return {
        "scenario": scenario.name,
        "nodes": len(node_ids),
        "physical_links": len(links),
        "ordered_endpoint_pairs": len(node_ids) * (len(node_ids) - 1),
        "total_cases": total_cases,
        "passed_cases": delivered_cases,
        "failed_cases": len(failures),
        "failures": failures,
    }
