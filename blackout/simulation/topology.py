"""Deterministic range-based contacts and forced link availability."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import combinations

from blackout.events import EventType
from blackout.models import Node
from blackout.simulation.engine import SimulationEngine

type Link = tuple[str, str]


def canonical_link(node_a: str, node_b: str) -> Link:
    """Return one stable identity for an undirected link."""

    if not node_a or not node_b:
        raise ValueError("link endpoints must not be empty")
    if node_a == node_b:
        raise ValueError("a link must connect two different nodes")
    return (node_a, node_b) if node_a < node_b else (node_b, node_a)


class TopologyManager:
    """Track active contacts derived from geometry, health, and forced failures."""

    def __init__(self, nodes: Mapping[str, Node], blocked_links: Iterable[Link] = ()) -> None:
        self._nodes = nodes
        self._active_contacts: set[Link] = set()
        self._blocked_links: set[Link] = set()
        for node_a, node_b in blocked_links:
            link = self._validated_link(node_a, node_b)
            self._blocked_links.add(link)

    @property
    def active_contacts(self) -> frozenset[Link]:
        return frozenset(self._active_contacts)

    @property
    def blocked_links(self) -> frozenset[Link]:
        return frozenset(self._blocked_links)

    def is_link_active(self, node_a: str, node_b: str) -> bool:
        return canonical_link(node_a, node_b) in self._active_contacts

    def is_link_blocked(self, node_a: str, node_b: str) -> bool:
        return canonical_link(node_a, node_b) in self._blocked_links

    def reconcile(
        self,
        at_time: float,
        engine: SimulationEngine,
        *,
        reason: str = "range_update",
    ) -> None:
        """Make active contacts match the current node and failure state."""

        desired = self._desired_contacts()
        ended = sorted(self._active_contacts - desired)
        started = sorted(desired - self._active_contacts)

        for link in ended:
            self._end_contact(link, at_time, engine, reason)
        for link in started:
            self._start_contact(link, at_time, engine, reason)

    def fail_link(
        self, node_a: str, node_b: str, at_time: float, engine: SimulationEngine
    ) -> None:
        self._blocked_links.add(self._validated_link(node_a, node_b))
        self.reconcile(at_time, engine, reason="forced_failure")

    def restore_link(
        self, node_a: str, node_b: str, at_time: float, engine: SimulationEngine
    ) -> None:
        self.clear_failure(node_a, node_b)
        self.reconcile(at_time, engine, reason="link_restored")

    def clear_failure(self, node_a: str, node_b: str) -> None:
        self._blocked_links.discard(self._validated_link(node_a, node_b))

    def _desired_contacts(self) -> set[Link]:
        desired: set[Link] = set()
        for node_a_id, node_b_id in combinations(sorted(self._nodes), 2):
            link = (node_a_id, node_b_id)
            node_a = self._nodes[node_a_id]
            node_b = self._nodes[node_b_id]
            if (
                link not in self._blocked_links
                and node_a.is_available
                and node_b.is_available
                and node_a.in_range_of(node_b)
            ):
                desired.add(link)
        return desired

    def _start_contact(
        self, link: Link, at_time: float, engine: SimulationEngine, reason: str
    ) -> None:
        node_a, node_b = (self._nodes[node_id] for node_id in link)
        node_a.start_contact(node_b.node_id, at_time)
        node_b.start_contact(node_a.node_id, at_time)
        self._active_contacts.add(link)
        engine.schedule(
            EventType.CONTACT_STARTED,
            {
                "node_a": node_a.node_id,
                "node_b": node_b.node_id,
                "distance": node_a.distance_to(node_b),
                "reason": reason,
            },
        )

    def _end_contact(
        self, link: Link, at_time: float, engine: SimulationEngine, reason: str
    ) -> None:
        node_a, node_b = (self._nodes[node_id] for node_id in link)
        record = node_a.end_contact(node_b.node_id, at_time)
        node_b.end_contact(node_a.node_id, at_time)
        self._active_contacts.remove(link)
        engine.schedule(
            EventType.CONTACT_ENDED,
            {
                "node_a": node_a.node_id,
                "node_b": node_b.node_id,
                "duration_seconds": record.ended_at - record.started_at,
                "reason": reason,
            },
        )

    def _validated_link(self, node_a: str, node_b: str) -> Link:
        link = canonical_link(node_a, node_b)
        unknown = [node_id for node_id in link if node_id not in self._nodes]
        if unknown:
            raise ValueError(f"link references unknown node {unknown[0]!r}")
        return link
