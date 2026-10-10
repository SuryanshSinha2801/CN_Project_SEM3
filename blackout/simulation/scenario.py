"""Translate validated scenario configuration into initial engine events."""

from __future__ import annotations

from blackout.config import ScenarioConfig
from blackout.events import EventType
from blackout.simulation.engine import SimulationEngine


def schedule_scenario(scenario: ScenarioConfig) -> SimulationEngine:
    """Create an engine and schedule all configuration-defined lifecycle events."""

    engine = SimulationEngine(seed=scenario.seed)
    engine.schedule_at(
        0,
        EventType.SIMULATION_STARTED,
        {"scenario_name": scenario.name, "seed": scenario.seed},
    )

    for message in scenario.messages:
        identity = {"message_id": message.message_id, "copy_id": "original"}
        engine.schedule_at(
            message.creation_time,
            EventType.MESSAGE_CREATED,
            {
                **identity,
                "source": message.source,
                "destination": message.destination,
                "size_bytes": message.size_bytes,
                "ttl_seconds": message.ttl_seconds,
            },
        )
        expiry_time = message.creation_time + message.ttl_seconds
        if expiry_time <= scenario.duration_seconds:
            engine.schedule_at(expiry_time, EventType.MESSAGE_EXPIRED, identity)

    for failure in scenario.forced_link_failures:
        link = {"node_a": failure.node_a, "node_b": failure.node_b}
        engine.schedule_at(failure.start_time, EventType.LINK_FAILED, link)
        engine.schedule_at(failure.end_time, EventType.LINK_RESTORED, link)

    engine.schedule_at(
        scenario.duration_seconds,
        EventType.SIMULATION_ENDED,
        {"scenario_name": scenario.name},
    )
    return engine
