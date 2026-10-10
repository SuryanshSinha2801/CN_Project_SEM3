"""Run scenarios repeatedly and export auditable comparison artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from blackout.config import RoutingPolicy, ScenarioConfig
from blackout.metrics import MetricsSummary, collect_metrics
from blackout.simulation import ScenarioSimulation, build_simulation


def export_run(
    simulation: ScenarioSimulation, output_directory: str | Path
) -> MetricsSummary:
    """Export one completed run as an event CSV and metrics JSON."""

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    summary = collect_metrics(simulation)
    stem = f"{summary.routing_policy}-seed-{summary.seed}"
    event_path = output_path / f"{stem}-events.csv"
    with event_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["event_time", "sequence_number", "event_type", "payload_json"],
        )
        writer.writeheader()
        for event in simulation.engine.event_log:
            writer.writerow(
                {
                    "event_time": event.event_time,
                    "sequence_number": event.sequence_number,
                    "event_type": event.event_type.value,
                    "payload_json": json.dumps(dict(event.payload), sort_keys=True),
                }
            )
    with (output_path / f"{stem}-metrics.json").open("w", encoding="utf-8") as stream:
        json.dump(summary.to_dict(), stream, indent=2, sort_keys=True)
    return summary


def run_matrix(
    scenario: ScenarioConfig,
    seeds: Iterable[int],
    policies: Iterable[RoutingPolicy],
    output_directory: str | Path,
) -> tuple[MetricsSummary, ...]:
    """Replay a common scenario for every seed and routing policy."""

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    results: list[MetricsSummary] = []
    for seed in seeds:
        for policy in policies:
            run_config = scenario.model_copy(
                update={"seed": seed, "routing_policy": policy}
            )
            simulation = build_simulation(run_config)
            simulation.run()
            results.append(export_run(simulation, output_path / "runs"))

    rows = [result.to_dict() for result in results]
    if rows:
        with (output_path / "comparison.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        _write_comparison_svg(results, output_path / "delivery-comparison.svg")
    return tuple(results)


def _write_comparison_svg(results: list[MetricsSummary], path: Path) -> None:
    """Write a dependency-free delivery-ratio bar chart as SVG."""

    by_policy: dict[str, list[float]] = {}
    for result in results:
        by_policy.setdefault(result.routing_policy, []).append(result.delivery_ratio)
    averages = {
        policy: sum(values) / len(values) for policy, values in by_policy.items()
    }
    width, height = 720, 420
    chart_left, chart_top, chart_height = 80, 45, 300
    chart_width = 590
    bar_slot = chart_width / max(1, len(averages))
    colors = ["#3b82f6", "#22c55e", "#f59e0b"]
    elements = [
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        '<text x="360" y="25" text-anchor="middle" '
        'font-family="Segoe UI" font-size="18" font-weight="bold">'
        "Delivery Ratio by Routing Policy</text>",
        f'<line x1="{chart_left}" y1="{chart_top}" x2="{chart_left}" '
        f'y2="{chart_top + chart_height}" stroke="#334155"/>',
        f'<line x1="{chart_left}" y1="{chart_top + chart_height}" '
        f'x2="{chart_left + chart_width}" y2="{chart_top + chart_height}" '
        'stroke="#334155"/>',
    ]
    for tick in range(6):
        value = tick / 5
        y = chart_top + chart_height * (1 - value)
        elements.append(
            f'<text x="68" y="{y + 4:.1f}" text-anchor="end" '
            f'font-family="Segoe UI" font-size="11">{value:.1f}</text>'
        )
    for index, (policy, value) in enumerate(sorted(averages.items())):
        bar_width = bar_slot * 0.55
        x = chart_left + index * bar_slot + (bar_slot - bar_width) / 2
        bar_height = value * chart_height
        y = chart_top + chart_height - bar_height
        color = colors[index % len(colors)]
        elements.extend(
            [
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                f'height="{bar_height:.1f}" fill="{color}"/>',
                f'<text x="{x + bar_width / 2:.1f}" y="{y - 7:.1f}" '
                f'text-anchor="middle" font-family="Segoe UI" font-size="12">'
                f"{value:.2f}</text>",
                f'<text x="{x + bar_width / 2:.1f}" y="{chart_top + chart_height + 24}" '
                f'text-anchor="middle" font-family="Segoe UI" font-size="12">'
                f"{policy}</text>",
            ]
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">' + "".join(elements) + "</svg>"
    )
    path.write_text(svg, encoding="utf-8")

