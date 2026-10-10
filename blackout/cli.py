"""Small command-line entry point used before the graphical application exists."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from blackout.config import load_scenario


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blackout", description="BLACKOUT project utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate and summarize a scenario")
    validate.add_argument("scenario", type=Path, help="path to a YAML scenario")

    gui = subparsers.add_parser("gui", help="open the Tkinter simulation demonstrator")
    gui.add_argument(
        "scenario",
        type=Path,
        nargs="?",
        default=Path("configs/presentation.yaml"),
        help="scenario YAML (default: configs/presentation.yaml)",
    )
    return parser


def validate_command(path: Path, console: Console) -> int:
    try:
        scenario = load_scenario(path)
    except (OSError, ValueError, ValidationError) as exc:
        console.print(f"[bold red]Invalid scenario:[/bold red] {exc}")
        return 1

    table = Table(title="Validated BLACKOUT scenario")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Name", scenario.name)
    table.add_row("Seed", str(scenario.seed))
    table.add_row("Duration", f"{scenario.duration_seconds:g} simulated seconds")
    table.add_row("Nodes", str(len(scenario.nodes)))
    table.add_row("Messages", str(len(scenario.messages)))
    table.add_row("Scripted movements", str(len(scenario.movements)))
    table.add_row("Routing policy", scenario.routing_policy.value)
    table.add_row("Forced failures", str(len(scenario.forced_link_failures)))
    console.print(table)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    if args.command == "validate":
        return validate_command(args.scenario, console)
    if args.command == "gui":
        from blackout.gui import launch_gui

        launch_gui(args.scenario)
        return 0
    return 2
