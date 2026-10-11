import csv
import json
from pathlib import Path

import pytest

from blackout.config import RoutingPolicy, load_scenario
from blackout.experiments import export_run, run_matrix
from blackout.metrics import collect_metrics
from blackout.simulation import build_simulation


def test_metrics_match_successful_presentation_trace() -> None:
    simulation = build_simulation(load_scenario("configs/presentation.yaml"))
    simulation.run()

    summary = collect_metrics(simulation)

    assert summary.generated_messages == 1
    assert summary.delivered_messages == 1
    assert summary.delivery_ratio == 1
    assert summary.average_delay_seconds == 5.5
    assert summary.average_hop_count == 5
    assert summary.successful_transfers == 5
    assert summary.failed_transfers == 1
    assert summary.routing_copies == 0
    assert summary.link_retransmissions == 0
    assert summary.routing_overhead_ratio == 4
    assert summary.delivered_payload_bytes == 1024
    assert summary.throughput_bytes_per_second == 1024 / 18
    assert summary.average_buffer_utilization == pytest.approx(5.5 * 0.125 / (18 * 12))
    assert summary.peak_buffer_utilization == 0.125


def test_export_run_writes_event_csv_and_metrics_json(tmp_path: Path) -> None:
    simulation = build_simulation(load_scenario("configs/presentation.yaml"))
    simulation.run()

    summary = export_run(simulation, tmp_path)

    metrics_path = tmp_path / "adaptive-seed-2801-metrics.json"
    event_path = tmp_path / "adaptive-seed-2801-events.csv"
    assert metrics_path.exists()
    assert event_path.exists()
    assert json.loads(metrics_path.read_text(encoding="utf-8"))["delivery_ratio"] == 1
    with event_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(simulation.engine.event_log)
    assert summary.routing_policy == "adaptive"


def test_matrix_exports_all_policies_and_svg_chart(tmp_path: Path) -> None:
    scenario = load_scenario("configs/presentation.yaml")

    results = run_matrix(
        scenario,
        seeds=[1],
        policies=list(RoutingPolicy),
        output_directory=tmp_path,
    )

    assert len(results) == 3
    assert {result.routing_policy for result in results} == {
        "adaptive",
        "epidemic",
        "spray_and_wait",
    }
    assert (tmp_path / "comparison.csv").exists()
    chart = tmp_path / "delivery-comparison.svg"
    assert chart.exists()
    assert "Delivery Ratio by Routing Policy" in chart.read_text(encoding="utf-8")
