"""Definitions and collection of reproducible BLACKOUT experiment metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any

from blackout.events import EventType
from blackout.simulation.runtime import ScenarioSimulation


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    scenario_name: str
    routing_policy: str
    seed: int
    generated_messages: int
    delivered_messages: int
    expired_messages: int
    delivery_ratio: float
    average_delay_seconds: float | None
    average_hop_count: float | None
    successful_transfers: int
    failed_transfers: int
    routing_copies: int
    link_retransmissions: int
    routing_overhead_ratio: float | None
    delivered_payload_bytes: int
    throughput_bytes_per_second: float
    average_buffer_utilization: float
    peak_buffer_utilization: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_metrics(simulation: ScenarioSimulation) -> MetricsSummary:
    """Calculate documented metrics from the event trace without changing the run."""

    events = simulation.engine.event_log
    generated_ids = {
        str(event.payload["message_id"])
        for event in events
        if event.event_type is EventType.MESSAGE_CREATED
    }
    deliveries = [event for event in events if event.event_type is EventType.MESSAGE_DELIVERED]
    delivered_ids = {str(event.payload["message_id"]) for event in deliveries}
    delays = [float(event.payload["delay_seconds"]) for event in deliveries]
    hops = [int(event.payload["hop_count"]) for event in deliveries]
    delivered_bytes = sum(int(event.payload["size_bytes"]) for event in deliveries)
    successful_transfers = sum(
        event.event_type is EventType.TRANSFER_COMPLETED for event in events
    )
    failed_transfers = sum(event.event_type is EventType.TRANSFER_FAILED for event in events)
    routing_copies = sum(
        event.event_type is EventType.ROUTING_COPY_CREATED for event in events
    )
    retransmissions = sum(event.event_type is EventType.RETRANSMISSION for event in events)
    generated = len(generated_ids)
    delivered = len(delivered_ids)
    expired_ids = {
        str(event.payload["message_id"])
        for event in events
        if event.event_type is EventType.MESSAGE_EXPIRED
    }
    expired = len(expired_ids - delivered_ids)
    overhead = (
        (successful_transfers - delivered) / delivered if delivered > 0 else None
    )
    buffer_events = [
        event
        for event in events
        if event.event_type in {EventType.MESSAGE_BUFFERED, EventType.BUFFER_UPDATED}
    ]
    utilization_by_node = {node_id: 0.0 for node_id in simulation.nodes}
    last_time_by_node = {node_id: 0.0 for node_id in simulation.nodes}
    utilization_area = {node_id: 0.0 for node_id in simulation.nodes}
    peak_buffer_utilization = 0.0
    for event in buffer_events:
        node_id = str(event.payload["node_id"])
        utilization_area[node_id] += utilization_by_node[node_id] * (
            event.event_time - last_time_by_node[node_id]
        )
        capacity = float(event.payload["used_bytes"]) + float(event.payload["free_bytes"])
        utilization = float(event.payload["used_bytes"]) / capacity
        utilization_by_node[node_id] = utilization
        last_time_by_node[node_id] = event.event_time
        peak_buffer_utilization = max(peak_buffer_utilization, utilization)
    for node_id in utilization_by_node:
        utilization_area[node_id] += utilization_by_node[node_id] * (
            simulation.scenario.duration_seconds - last_time_by_node[node_id]
        )
    average_buffer_utilization = sum(utilization_area.values()) / (
        simulation.scenario.duration_seconds * len(simulation.nodes)
    )
    return MetricsSummary(
        scenario_name=simulation.scenario.name,
        routing_policy=simulation.scenario.routing_policy.value,
        seed=simulation.scenario.seed,
        generated_messages=generated,
        delivered_messages=delivered,
        expired_messages=expired,
        delivery_ratio=delivered / generated if generated else 0.0,
        average_delay_seconds=fmean(delays) if delays else None,
        average_hop_count=fmean(hops) if hops else None,
        successful_transfers=successful_transfers,
        failed_transfers=failed_transfers,
        routing_copies=routing_copies,
        link_retransmissions=retransmissions,
        routing_overhead_ratio=overhead,
        delivered_payload_bytes=delivered_bytes,
        throughput_bytes_per_second=(
            delivered_bytes / simulation.scenario.duration_seconds
        ),
        average_buffer_utilization=average_buffer_utilization,
        peak_buffer_utilization=peak_buffer_utilization,
    )
