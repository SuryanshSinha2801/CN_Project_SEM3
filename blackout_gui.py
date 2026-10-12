"""Portable Windows entry point for the BLACKOUT Tkinter demonstrator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from blackout.config import load_scenario
from blackout.gui import launch_gui
from blackout.models import MessageState
from blackout.simulation import build_simulation
from blackout.verification import run_exhaustive_rerouting_check


def bundled_path(relative_path: str) -> Path:
    """Resolve project data both from source and a PyInstaller bundle."""

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def main() -> int:
    scenario_path = bundled_path("configs/presentation.yaml")
    if "--exhaustive-test" in sys.argv:
        report = run_exhaustive_rerouting_check(load_scenario(scenario_path))
        report_path = Path.cwd() / "BLACKOUT_exhaustive_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0 if report["failed_cases"] == 0 else 1
    if "--smoke-test" in sys.argv:
        simulation = build_simulation(load_scenario(scenario_path))
        simulation.run()
        if not any(
            message.state is MessageState.DELIVERED
            for message in simulation.messages.values()
        ):
            return 1
        return 0
    launch_gui(scenario_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
