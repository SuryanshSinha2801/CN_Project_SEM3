"""Presentation-oriented Tkinter observer for the BLACKOUT simulator."""

from __future__ import annotations

import tkinter as tk
from itertools import combinations
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from blackout.config import MessageConfig, ScenarioConfig, load_scenario
from blackout.events import EventType, SimulationEvent
from blackout.models import MessageState, NodeState
from blackout.simulation import ScenarioSimulation, build_simulation

CANVAS_WIDTH = 760
CANVAS_HEIGHT = 520
NODE_RADIUS = 24
LINK_SEPARATOR = " — "


def format_link(link: tuple[str, str]) -> str:
    """Format an undirected link for the GUI selector."""

    return LINK_SEPARATOR.join(link)


def parse_link(value: str) -> tuple[str, str]:
    """Parse a link selected in the GUI."""

    endpoints = tuple(part.strip() for part in value.split(LINK_SEPARATOR))
    if len(endpoints) != 2 or not all(endpoints) or endpoints[0] == endpoints[1]:
        raise ValueError("Select a valid link to fail")
    return endpoints[0], endpoints[1]


def build_interactive_scenario(
    base: ScenarioConfig, content: str, source: str, destination: str
) -> ScenarioConfig:
    """Create a validated one-message scenario from GUI input."""

    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("Enter a message before starting the simulation")
    known_nodes = {node.node_id for node in base.nodes}
    if source not in known_nodes or destination not in known_nodes:
        raise ValueError("Select valid source and destination nodes")
    if source == destination:
        raise ValueError("Source and destination must be different")
    encoded_size = len(normalized_content.encode("utf-8"))
    # Model one 1 KiB application packet so short demo text still has realistic
    # buffer cost and produces the same Adaptive-routing behavior as the scenario.
    size_bytes = max(1024, encoded_size)
    source_node = next(node for node in base.nodes if node.node_id == source)
    if size_bytes > source_node.buffer_capacity_bytes:
        raise ValueError(
            f"Message packet is {size_bytes} bytes but node {source} can store only "
            f"{source_node.buffer_capacity_bytes} bytes"
        )
    message = MessageConfig(
        message_id="interactive-message",
        source=source,
        destination=destination,
        size_bytes=size_bytes,
        creation_time=0,
        ttl_seconds=base.duration_seconds,
        content=normalized_content,
    )
    return base.model_copy(
        update={
            "name": f"{base.name}-interactive",
            "messages": (message,),
            # Keep background exclusions that shape the demo topology, while
            # replacing timed scripted failures with live random failures.
            "forced_link_failures": tuple(
                failure
                for failure in base.forced_link_failures
                if failure.start_time == 0
            ),
        }
    )


def event_summary(event: SimulationEvent) -> str:
    """Return a compact, professor-friendly description of an event."""

    payload = event.payload
    event_type = event.event_type
    if event_type in {EventType.CONTACT_STARTED, EventType.CONTACT_ENDED}:
        return (
            f"topology only: {payload['node_a']} ↔ {payload['node_b']} "
            "(no message sent)"
        )
    if event_type in {EventType.LINK_FAILED, EventType.LINK_RESTORED}:
        if payload.get("random_failure"):
            kind = "random"
        elif payload.get("manual_failure"):
            kind = "selected"
        else:
            kind = "scripted"
        return f"{payload['node_a']}-{payload['node_b']} ({kind})"
    if event_type is EventType.FORWARD_DECISION:
        target = payload.get("to_node") or "none"
        return f"{payload['action']}: {payload['from_node']} → {target} — {payload['reason']}"
    if event_type in {
        EventType.TRANSFER_COMPLETED,
        EventType.TRANSFER_FAILED,
        EventType.TRANSFER_ATTEMPT,
        EventType.PACKET_SENT,
        EventType.PACKET_RECEIVED,
        EventType.PACKET_LOST,
        EventType.ACK_SENT,
        EventType.ACK_RECEIVED,
        EventType.ACK_LOST,
        EventType.RETRANSMISSION,
    }:
        return f"{payload['from_node']} → {payload['to_node']} ({payload['message_id']})"
    if event_type is EventType.ROUTING_COPY_CREATED:
        return (
            f"copy {payload['copy_id']}: {payload['from_node']} → "
            f"{payload['to_node']}"
        )
    if event_type is EventType.BUFFER_UPDATED:
        return (
            f"{payload['node_id']}: {payload['used_bytes']} B used, "
            f"{payload['free_bytes']} B free"
        )
    if event_type in {
        EventType.MESSAGE_CREATED,
        EventType.MESSAGE_BUFFERED,
        EventType.MESSAGE_EXPIRED,
        EventType.MESSAGE_DELIVERED,
    }:
        location = payload.get("node_id") or payload.get("source") or ""
        return f"{payload['message_id']} {location}".strip()
    return str(payload.get("scenario_name", ""))


class BlackoutApp:
    """Render simulation snapshots without controlling simulation decisions."""

    def __init__(self, root: tk.Tk, scenario_path: Path) -> None:
        self.root = root
        self.scenario_path = scenario_path
        self.scenario = load_scenario(scenario_path)
        self.simulation: ScenarioSimulation = build_simulation(self.scenario)
        self.playing = False
        self.after_id: str | None = None
        self.next_random_failure_time: float | None = None
        self.delivery_complete = False

        root.title("BLACKOUT — Delay-Tolerant Network Simulation")
        root.geometry("1280x760")
        root.minsize(1050, 680)
        self._configure_style()
        self._build_layout()
        self._render()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def _build_layout(self) -> None:
        header = ttk.Frame(self.root, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="BLACKOUT Network Simulator", style="Title.TLabel").pack(
            side="left"
        )
        self.status_var = tk.StringVar(value="Ready — press Step or Play")
        ttk.Label(header, textvariable=self.status_var).pack(side="right")

        controls = ttk.Frame(self.root, padding=(16, 0, 16, 10))
        controls.pack(fill="x")
        ttk.Button(
            controls, text="▶ Play", style="Accent.TButton", command=self.toggle_play
        ).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Step Event", command=self.step).pack(side="left", padx=6)
        ttk.Button(controls, text="Reset", command=self.reset).pack(side="left", padx=6)
        ttk.Label(controls, text="Speed:").pack(side="left", padx=(24, 4))
        self.speed_var = tk.DoubleVar(value=1.0)
        ttk.Scale(
            controls,
            from_=0.25,
            to=3.0,
            variable=self.speed_var,
            orient="horizontal",
            length=150,
        ).pack(side="left")
        ttk.Label(
            controls,
            text=(
                "Green = radio proximity only   Red dashed = failed link   "
                "Gold arrow = actual message route"
            ),
        ).pack(side="right")

        composer = ttk.LabelFrame(
            self.root, text="Interactive message and rerouting", padding=8
        )
        composer.pack(fill="x", padx=16, pady=(0, 10))
        message_row = ttk.Frame(composer)
        message_row.pack(fill="x", pady=(0, 6))
        action_row = ttk.Frame(composer)
        action_row.pack(fill="x")
        ttk.Label(message_row, text="Message:").pack(side="left")
        self.message_var = tk.StringVar(value="Emergency data: alternate route required")
        ttk.Entry(message_row, textvariable=self.message_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )
        node_ids = [node.node_id for node in self.scenario.nodes]
        ttk.Label(action_row, text="Source:").pack(side="left")
        self.source_var = tk.StringVar(value=node_ids[0])
        source_box = ttk.Combobox(
            action_row,
            textvariable=self.source_var,
            values=node_ids,
            state="readonly",
            width=6,
        )
        source_box.pack(side="left", padx=(4, 12))
        ttk.Label(action_row, text="Destination:").pack(side="left")
        default_destination = "D" if "D" in node_ids else node_ids[-1]
        self.destination_var = tk.StringVar(value=default_destination)
        destination_box = ttk.Combobox(
            action_row,
            textvariable=self.destination_var,
            values=node_ids,
            state="readonly",
            width=6,
        )
        destination_box.pack(side="left", padx=(4, 12))
        self.auto_failures_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            action_row,
            text="Automatic random failures",
            variable=self.auto_failures_var,
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            action_row,
            text="Start Custom Message",
            style="Accent.TButton",
            command=self.start_custom_message,
        ).pack(side="left", padx=(0, 6))
        failure_row = ttk.Frame(composer)
        failure_row.pack(fill="x", pady=(7, 0))
        ttk.Label(failure_row, text="Link to fail:").pack(side="left")
        self.link_var = tk.StringVar()
        self.link_box = ttk.Combobox(
            failure_row,
            textvariable=self.link_var,
            state="readonly",
            width=12,
        )
        self.link_box.pack(side="left", padx=(4, 8))
        ttk.Button(
            failure_row,
            text="Break Selected Link (5s)",
            command=self.break_selected_link,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            failure_row,
            text="Break Random Link",
            command=self.break_random_link,
        ).pack(side="left")
        ttk.Label(
            failure_row,
            text="Choose a green link, or keep the seeded random failure.",
        ).pack(side="left", padx=(12, 0))

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        network_frame = ttk.LabelFrame(body, text="Network topology", padding=6)
        details_frame = ttk.Frame(body)
        body.add(network_frame, weight=3)
        body.add(details_frame, weight=2)

        self.canvas = tk.Canvas(
            network_frame,
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            background="#101827",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        metrics = ttk.LabelFrame(details_frame, text="Simulation state", padding=10)
        metrics.pack(fill="x", pady=(0, 8))
        self.metrics_var = tk.StringVar()
        ttk.Label(metrics, textvariable=self.metrics_var, justify="left").pack(anchor="w")

        decision = ttk.LabelFrame(
            details_frame, text="Latest routing decision", padding=10
        )
        decision.pack(fill="x", pady=(0, 8))
        self.decision_var = tk.StringVar(
            value="No routing decision yet.\nC=connectivity, P=proximity, B=buffer, S=node state."
        )
        ttk.Label(
            decision,
            textvariable=self.decision_var,
            justify="left",
            wraplength=410,
        ).pack(anchor="w")

        events = ttk.LabelFrame(details_frame, text="Event trace", padding=6)
        events.pack(fill="both", expand=True)
        self.event_tree = ttk.Treeview(
            events,
            columns=("time", "event", "details"),
            show="headings",
            height=18,
        )
        self.event_tree.heading("time", text="Time")
        self.event_tree.heading("event", text="Event")
        self.event_tree.heading("details", text="Details")
        self.event_tree.column("time", width=55, anchor="center", stretch=False)
        self.event_tree.column("event", width=145, stretch=False)
        self.event_tree.column("details", width=300)
        scrollbar = ttk.Scrollbar(events, orient="vertical", command=self.event_tree.yview)
        self.event_tree.configure(yscrollcommand=scrollbar.set)
        self.event_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def step(self) -> None:
        if self.delivery_complete:
            self.status_var.set("Message already delivered — reset or start a new message")
            return
        event = self.simulation.step()
        if event is None:
            self.playing = False
            self.status_var.set("Simulation complete")
            return
        self._record_event(event)
        if event.event_type is EventType.MESSAGE_DELIVERED:
            self.playing = False
            self.delivery_complete = True
            self.status_var.set(
                f"Delivered to {event.payload['node_id']} — routing stopped"
            )
        else:
            self._maybe_inject_random_failure()
        self._render()

    def start_custom_message(self) -> None:
        """Rebuild the simulation with user-selected message endpoints."""

        try:
            self.scenario = build_interactive_scenario(
                load_scenario(self.scenario_path),
                self.message_var.get(),
                self.source_var.get(),
                self.destination_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid interactive message", str(exc))
            return
        self.playing = False
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.simulation = build_simulation(self.scenario)
        self.next_random_failure_time = 0 if self.auto_failures_var.get() else None
        self.delivery_complete = False
        self._clear_trace()
        self.status_var.set(
            f"Custom message ready: {self.source_var.get()} → "
            f"{self.destination_var.get()} — press Play"
        )
        self._render()

    def break_random_link(self) -> None:
        """Fail one currently active contact using the scenario's seeded RNG."""

        link = self.simulation.break_random_active_link(duration_seconds=3)
        if link is None:
            self.status_var.set("No active link is currently available to break")
            return
        self.status_var.set(
            f"Random failure queued for {link[0]}-{link[1]}; rerouting will be detected"
        )

    def break_selected_link(self) -> None:
        """Fail the physical link selected by the presenter for five seconds."""

        try:
            node_a, node_b = parse_link(self.link_var.get())
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        link = self.simulation.break_link(node_a, node_b, duration_seconds=5)
        if link is None:
            self.status_var.set(
                f"Link {node_a}-{node_b} is unavailable or already failed"
            )
            return
        self.status_var.set(
            f"Selected failure queued for {link[0]}-{link[1]}; "
            "the router will find another path"
        )

    def _maybe_inject_random_failure(self) -> None:
        if self.next_random_failure_time is None:
            return
        now = self.simulation.engine.current_time
        if now < self.next_random_failure_time:
            return
        link = self.simulation.break_random_active_link(duration_seconds=8)
        # One automatic failure keeps the demonstration understandable and still
        # allows delivery. The presenter can inject additional failures manually.
        self.next_random_failure_time = None
        if link is not None:
            self.status_var.set(
                f"Auto failure: {link[0]}-{link[1]} broke; finding alternate route"
            )

    def toggle_play(self) -> None:
        self.playing = not self.playing
        if self.playing:
            self.status_var.set("Playing deterministic event trace")
            self._play_next()
        else:
            self.status_var.set("Paused")
            if self.after_id is not None:
                self.root.after_cancel(self.after_id)
                self.after_id = None

    def _play_next(self) -> None:
        if not self.playing:
            return
        before = len(self.simulation.engine.event_log)
        self.step()
        if not self._playback_is_active():
            return
        if len(self.simulation.engine.event_log) == before:
            return
        delay_ms = max(80, int(650 / self.speed_var.get()))
        self.after_id = self.root.after(delay_ms, self._play_next)

    def _playback_is_active(self) -> bool:
        """Read playback state after a step without retaining a stale type narrowing."""

        return self.playing

    def reset(self) -> None:
        self.playing = False
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.simulation.reset()
        self.delivery_complete = False
        self.next_random_failure_time = (
            0 if self.auto_failures_var.get() and "-interactive" in self.scenario.name else None
        )
        self._clear_trace()
        self.status_var.set("Reset complete — deterministic seed restored")
        self._render()

    def _clear_trace(self) -> None:
        for item in self.event_tree.get_children():
            self.event_tree.delete(item)
        self.decision_var.set(
            "No routing decision yet.\nC=connectivity, P=proximity, B=buffer, S=node state."
        )

    def _record_event(self, event: SimulationEvent) -> None:
        self.event_tree.insert(
            "",
            "end",
            values=(f"{event.event_time:g}", event.event_type.value, event_summary(event)),
        )
        children = self.event_tree.get_children()
        if len(children) > 250:
            self.event_tree.delete(children[0])
        self.event_tree.yview_moveto(1)
        self.status_var.set(f"t={event.event_time:g}s — {event.event_type.value}")
        if event.event_type is EventType.FORWARD_DECISION:
            self._show_decision(event.payload)

    def _show_decision(self, payload: Any) -> None:
        components = payload.get("score_components", {})
        holder = components.get("holder_total")
        candidate = components.get("candidate_total")
        threshold = components.get("minimum_improvement")
        candidate_factors = ""
        if "candidate_connectivity" in components:
            candidate_factors = (
                "\nCandidate factors: "
                f"C={components['candidate_connectivity']:.3f}, "
                f"P={components['candidate_proximity']:.3f}, "
                f"B={components['candidate_buffer_availability']:.3f}, "
                f"S={components['candidate_node_state']:.3f}"
            )
        score_line = ""
        if holder is not None:
            score_line = f"\nHolder score={holder:.3f}"
            if candidate is not None:
                score_line += f"  Candidate score={candidate:.3f}"
            if threshold is not None:
                score_line += f"  δ={threshold:.3f}"
        self.decision_var.set(
            f"{str(payload['action']).upper()}: {payload['from_node']} → "
            f"{payload.get('to_node') or 'hold'}\n{payload['reason']}"
            f"{score_line}{candidate_factors}"
        )

    def _render(self) -> None:
        snapshot = self.simulation.snapshot()
        self._update_link_choices(snapshot.active_contacts)
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), CANVAS_WIDTH)
        height = max(self.canvas.winfo_height(), CANVAS_HEIGHT)
        positions = {
            node.node_id: self._canvas_position(node.position.x, node.position.y, width, height)
            for node in snapshot.nodes
        }

        for node_a, node_b in sorted(self.simulation.topology.blocked_links):
            self._draw_link(positions[node_a], positions[node_b], "#ef4444", dash=(8, 5), width=3)
        for node_a, node_b in snapshot.active_contacts:
            self._draw_link(positions[node_a], positions[node_b], "#22c55e", width=3)

        route_hops = {
            hop
            for message in snapshot.messages
            for hop in message.route_hops
        }
        for node_a, node_b in sorted(route_hops):
            self._draw_link(
                positions[node_a],
                positions[node_b],
                "#facc15",
                width=5,
                arrow=True,
            )

        holders = {
            message.custody_holder
            for message in snapshot.messages
            if message.state is MessageState.BUFFERED
        }
        for node in snapshot.nodes:
            x, y = positions[node.node_id]
            color = {
                NodeState.HEALTHY: "#3b82f6",
                NodeState.DEGRADED: "#f59e0b",
                NodeState.UNAVAILABLE: "#64748b",
            }[node.state]
            if node.node_id in holders:
                self.canvas.create_oval(
                    x - NODE_RADIUS - 5,
                    y - NODE_RADIUS - 5,
                    x + NODE_RADIUS + 5,
                    y + NODE_RADIUS + 5,
                    outline="#facc15",
                    width=4,
                )
            self.canvas.create_oval(
                x - NODE_RADIUS,
                y - NODE_RADIUS,
                x + NODE_RADIUS,
                y + NODE_RADIUS,
                fill=color,
                outline="#e2e8f0",
                width=2,
            )
            self.canvas.create_text(
                x, y, text=node.node_id, fill="white", font=("Segoe UI", 12, "bold")
            )
            self.canvas.create_text(
                x,
                y + 38,
                text=f"Buffer {node.buffer_used_bytes}/{node.buffer_capacity_bytes} B",
                fill="#cbd5e1",
                font=("Segoe UI", 9),
            )

        delivered = sum(
            message.state is MessageState.DELIVERED for message in snapshot.messages
        )
        buffered = sum(
            message.state is MessageState.BUFFERED for message in snapshot.messages
        )
        expired = sum(message.state is MessageState.EXPIRED for message in snapshot.messages)
        self.metrics_var.set(
            f"Scenario: {self.scenario.name}\n"
            f"Simulated time: {snapshot.simulated_time:g} / {self.scenario.duration_seconds:g} s\n"
            f"Policy: {self.scenario.routing_policy.value}\n"
            f"Active contacts: {len(snapshot.active_contacts)}\n"
            f"Messages — buffered: {buffered}, delivered: {delivered}, expired: {expired}\n"
            f"Seed: {self.scenario.seed} (reproducible)"
        )

    def _update_link_choices(
        self, active_contacts: tuple[tuple[str, str], ...]
    ) -> None:
        """Keep the selector synchronized with usable physical links."""

        links = set(active_contacts)
        if not links:
            for node_a_id, node_b_id in combinations(sorted(self.simulation.nodes), 2):
                node_a = self.simulation.nodes[node_a_id]
                node_b = self.simulation.nodes[node_b_id]
                link = (node_a_id, node_b_id)
                if (
                    node_a.is_available
                    and node_b.is_available
                    and node_a.in_range_of(node_b)
                    and link not in self.simulation.topology.blocked_links
                ):
                    links.add(link)
        choices = tuple(format_link(link) for link in sorted(links))
        current = self.link_var.get()
        self.link_box.configure(values=choices)
        if current not in choices:
            self.link_var.set(choices[0] if choices else "")

    def _canvas_position(
        self, x: float, y: float, width: int, height: int
    ) -> tuple[float, float]:
        padding = 65
        usable_width = max(1, width - 2 * padding)
        usable_height = max(1, height - 2 * padding)
        return (
            padding + x / self.scenario.area.width * usable_width,
            padding + y / self.scenario.area.height * usable_height,
        )

    def _draw_link(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        color: str,
        *,
        dash: tuple[int, int] | None = None,
        width: int = 2,
        arrow: bool = False,
    ) -> None:
        coordinates = (start, end)
        if dash is not None and arrow:
            self.canvas.create_line(
                coordinates, fill=color, width=width, dash=dash, arrow="last"
            )
        elif dash is not None:
            self.canvas.create_line(coordinates, fill=color, width=width, dash=dash)
        elif arrow:
            self.canvas.create_line(coordinates, fill=color, width=width, arrow="last")
        else:
            self.canvas.create_line(coordinates, fill=color, width=width)


def launch_gui(scenario_path: str | Path) -> None:
    """Load a scenario and start the Tkinter presentation window."""

    root = tk.Tk()
    try:
        BlackoutApp(root, Path(scenario_path))
    except Exception as exc:
        root.withdraw()
        messagebox.showerror("BLACKOUT could not start", str(exc))
        root.destroy()
        raise
    root.mainloop()
