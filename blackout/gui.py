"""Presentation-oriented Tkinter observer for the BLACKOUT simulator."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from blackout.config import load_scenario
from blackout.events import EventType, SimulationEvent
from blackout.models import MessageState, NodeState
from blackout.simulation import ScenarioSimulation, build_simulation

CANVAS_WIDTH = 760
CANVAS_HEIGHT = 520
NODE_RADIUS = 24


def event_summary(event: SimulationEvent) -> str:
    """Return a compact, professor-friendly description of an event."""

    payload = event.payload
    event_type = event.event_type
    if event_type in {EventType.CONTACT_STARTED, EventType.CONTACT_ENDED}:
        return f"{payload['node_a']} ↔ {payload['node_b']}"
    if event_type in {EventType.LINK_FAILED, EventType.LINK_RESTORED}:
        return f"{payload['node_a']}–{payload['node_b']}"
    if event_type is EventType.FORWARD_DECISION:
        target = payload.get("to_node") or "none"
        return f"{payload['action']}: {payload['from_node']} → {target} — {payload['reason']}"
    if event_type in {
        EventType.TRANSFER_COMPLETED,
        EventType.TRANSFER_FAILED,
        EventType.TRANSFER_ATTEMPT,
    }:
        return f"{payload['from_node']} → {payload['to_node']} ({payload['message_id']})"
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

        root.title("BLACKOUT — Adaptive Network Simulation")
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
                "Green = active contact   Red dashed = forced failure   "
                "Gold ring = message custodian"
            ),
        ).pack(side="right")

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
            details_frame, text="Latest Adaptive decision", padding=10
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
        event = self.simulation.step()
        if event is None:
            self.playing = False
            self.status_var.set("Simulation complete")
            return
        self._record_event(event)
        self._render()

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
        if len(self.simulation.engine.event_log) == before:
            return
        delay_ms = max(80, int(650 / self.speed_var.get()))
        self.after_id = self.root.after(delay_ms, self._play_next)

    def reset(self) -> None:
        self.playing = False
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.simulation.reset()
        for item in self.event_tree.get_children():
            self.event_tree.delete(item)
        self.decision_var.set(
            "No routing decision yet.\nC=connectivity, P=proximity, B=buffer, S=node state."
        )
        self.status_var.set("Reset complete — deterministic seed restored")
        self._render()

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
            f"Policy: BLACKOUT Adaptive (single-copy)\n"
            f"Active contacts: {len(snapshot.active_contacts)}\n"
            f"Messages — buffered: {buffered}, delivered: {delivered}, expired: {expired}\n"
            f"Seed: {self.scenario.seed} (reproducible)"
        )

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
    ) -> None:
        self.canvas.create_line(*start, *end, fill=color, width=width, dash=dash)


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

