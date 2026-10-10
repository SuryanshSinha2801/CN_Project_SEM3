"""Deterministic simulated-time event engine for BLACKOUT."""

from __future__ import annotations

import heapq
import math
import random
from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Any

from blackout.events import EventType, SimulationEvent

type EventHandler = Callable[[SimulationEvent, "SimulationEngine"], None]


class SimulationEngine:
    """Run scheduled events without depending on wall-clock time.

    Each engine owns its random-number generator. Components must use ``engine.random``
    instead of the module-level ``random`` functions so a scenario can be replayed from
    its seed.
    """

    def __init__(self, seed: int) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self._seed = seed
        self._random = random.Random(seed)
        self._current_time = 0.0
        self._next_sequence_number = 0
        self._queue: list[SimulationEvent] = []
        self._event_log: list[SimulationEvent] = []
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def current_time(self) -> float:
        return self._current_time

    @property
    def random(self) -> random.Random:
        """Return the engine-local seeded random-number generator."""

        return self._random

    @property
    def pending_event_count(self) -> int:
        return len(self._queue)

    @property
    def event_log(self) -> tuple[SimulationEvent, ...]:
        """Return an immutable view of all processed events in execution order."""

        return tuple(self._event_log)

    def schedule_at(
        self,
        event_time: float,
        event_type: EventType,
        payload: Mapping[str, Any] | None = None,
    ) -> SimulationEvent:
        """Schedule an event at an absolute simulated time."""

        timestamp = float(event_time)
        if not math.isfinite(timestamp):
            raise ValueError("event time must be finite")
        if timestamp < self._current_time:
            raise ValueError("cannot schedule an event in the simulated past")

        event = SimulationEvent(
            event_time=timestamp,
            sequence_number=self._next_sequence_number,
            event_type=event_type,
            payload=dict(payload or {}),
        )
        self._next_sequence_number += 1
        heapq.heappush(self._queue, event)
        return event

    def schedule(
        self,
        event_type: EventType,
        payload: Mapping[str, Any] | None = None,
    ) -> SimulationEvent:
        """Schedule an event for the current simulated time."""

        return self.schedule_at(self._current_time, event_type, payload)

    def schedule_after(
        self,
        delay: float,
        event_type: EventType,
        payload: Mapping[str, Any] | None = None,
    ) -> SimulationEvent:
        """Schedule an event relative to the current simulated time."""

        relative_delay = float(delay)
        if not math.isfinite(relative_delay) or relative_delay < 0:
            raise ValueError("event delay must be finite and non-negative")
        return self.schedule_at(self._current_time + relative_delay, event_type, payload)

    def register_handler(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a callback invoked whenever ``event_type`` is processed."""

        self._handlers[event_type].append(handler)

    def cancel_scheduled(
        self,
        event_type: EventType,
        predicate: Callable[[SimulationEvent], bool] | None = None,
    ) -> int:
        """Cancel queued events of one type and return the number removed."""

        retained: list[SimulationEvent] = []
        removed = 0
        for event in self._queue:
            matches = event.event_type is event_type and (
                predicate is None or predicate(event)
            )
            if matches:
                removed += 1
            else:
                retained.append(event)
        if removed:
            self._queue = retained
            heapq.heapify(self._queue)
        return removed

    def step(self) -> SimulationEvent | None:
        """Process exactly one event, or return ``None`` when the queue is empty."""

        if not self._queue:
            return None

        event = heapq.heappop(self._queue)
        self._current_time = event.event_time
        self._event_log.append(event)
        for handler in tuple(self._handlers[event.event_type]):
            handler(event, self)
        return event

    def run(self, until: float | None = None) -> tuple[SimulationEvent, ...]:
        """Process queued events up to an optional inclusive time boundary.

        The return value contains only the events processed by this call. When ``until``
        is supplied, the clock advances to that boundary even if no event occurs there.
        """

        boundary = math.inf if until is None else float(until)
        if not math.isfinite(boundary) and until is not None:
            raise ValueError("run boundary must be finite")
        if boundary < self._current_time:
            raise ValueError("cannot run backwards in simulated time")

        log_start = len(self._event_log)
        while self._queue and self._queue[0].event_time <= boundary:
            self.step()
        if until is not None:
            self._current_time = boundary
        return tuple(self._event_log[log_start:])

    def reset(self) -> None:
        """Clear runtime state and rewind the seeded generator for an exact replay.

        Registered handlers remain installed because they represent the assembled model,
        while scheduled events and the trace belong to a particular run.
        """

        self._random.seed(self._seed)
        self._current_time = 0.0
        self._next_sequence_number = 0
        self._queue.clear()
        self._event_log.clear()
