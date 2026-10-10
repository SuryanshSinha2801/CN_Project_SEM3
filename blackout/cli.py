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

    run = subparsers.add_parser("run", help="run one scenario and export metrics/events")
    run.add_argument("scenario", type=Path, help="path to a YAML scenario")
    run.add_argument(
        "--output", type=Path, default=Path("results"), help="artifact output directory"
    )

    experiment = subparsers.add_parser(
        "experiment", help="compare routing policies over common random seeds"
    )
    experiment.add_argument("scenario", type=Path, help="base scenario YAML")
    experiment.add_argument(
        "--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5], help="random seeds"
    )
    experiment.add_argument(
        "--policies",
        nargs="+",
        choices=["adaptive", "epidemic", "spray_and_wait"],
        default=["adaptive", "epidemic", "spray_and_wait"],
    )
    experiment.add_argument(
        "--output",
        type=Path,
        default=Path("results/comparison"),
        help="artifact output directory",
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
    if args.command == "run":
        from blackout.experiments import export_run
        from blackout.simulation import build_simulation

        scenario = load_scenario(args.scenario)
        simulation = build_simulation(scenario)
        simulation.run()
        summary = export_run(simulation, args.output)
        _print_metrics(summary.to_dict(), console)
        console.print(f"[green]Artifacts written to {args.output.resolve()}[/green]")
        return 0
    if args.command == "experiment":
        from blackout.config import RoutingPolicy
        from blackout.experiments import run_matrix

        scenario = load_scenario(args.scenario)
        policies = [RoutingPolicy(policy) for policy in args.policies]
        results = run_matrix(scenario, args.seeds, policies, args.output)
        table = Table(title="BLACKOUT routing comparison")
        for column in ("Policy", "Seed", "Delivery", "Delay", "Copies", "Retries"):
            table.add_column(column)
        for result in results:
            table.add_row(
                result.routing_policy,
                str(result.seed),
                f"{result.delivery_ratio:.2f}",
                "n/a"
                if result.average_delay_seconds is None
                else f"{result.average_delay_seconds:.2f}",
                str(result.routing_copies),
                str(result.link_retransmissions),
            )
        console.print(table)
        console.print(f"[green]Comparison written to {args.output.resolve()}[/green]")
        return 0
    return 2


def _print_metrics(metrics: dict[str, object], console: Console) -> None:
    table = Table(title="BLACKOUT run metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    for name, value in metrics.items():
        table.add_row(name.replace("_", " ").title(), "n/a" if value is None else str(value))
    console.print(table)
