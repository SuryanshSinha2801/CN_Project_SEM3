# CN Project SEM3

BLACKOUT is a Python-based educational simulator for studying communication in intermittently connected and delay-tolerant networks. It demonstrates store-carry-forward delivery when links fail or a continuous source-to-destination path does not exist.

## Project status

The project has entered implementation. The repository now contains the approved modular design, validated YAML scenarios, a deterministic event engine, core domain models, range-based contacts, the full weighted BLACKOUT Adaptive policy, and a Tkinter presentation GUI. The next milestone is implementing the Epidemic and Binary Spray-and-Wait baselines.

## Planned capabilities

- Dynamic two-dimensional nodes and range-based contacts
- Node movement, link failures, packet loss, and temporary partitions
- Finite buffers and store-carry-forward delivery
- Epidemic Routing
- Binary Spray-and-Wait Routing
- Explainable BLACKOUT Adaptive Routing
- CRC, acknowledgements, timeouts, and retransmissions
- Stop-and-Wait and later Sliding Window demonstrations
- Reproducible scenario traces and random seeds
- Delivery, delay, hop, copy, overhead, buffer, and throughput metrics
- Pygame visualization and CSV/graph-based experiment reporting

## Architecture

See [BLACKOUT_ARCHITECTURE.md](BLACKOUT_ARCHITECTURE.md) for:

- High-level architecture and runtime data flow
- Python package responsibilities and interfaces
- Message, packet, node, link, and buffer models
- The Adaptive forwarding score
- Routing baseline definitions
- MVP acceptance tests
- Fair experimental methodology
- Risks and implementation order

## Technology stack

- CPython 3.13
- Tkinter (included with the standard Python Windows installation) for the current GUI
- Pygame Community Edition for the planned advanced animated interface
- PyYAML and Pydantic
- NumPy, Pandas, and Matplotlib
- Rich
- Pytest, pytest-cov, and Hypothesis
- Ruff and Mypy

Exact versions and dependency explanations are in [requirement.txt](requirement.txt).

## Local setup

```powershell
git clone https://github.com/SuryanshSinha2801/CN_Project_SEM3.git
cd CN_Project_SEM3
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirement.txt
```

Verify the environment:

```powershell
python -c "import pygame, numpy, pandas, matplotlib, yaml, pydantic; print('BLACKOUT dependencies OK')"
pytest --version
ruff --version
```

Validate the supplied scenarios:

```powershell
python -m blackout validate configs/default.yaml
python -m blackout validate configs/broken_route.yaml
python -m blackout validate configs/presentation.yaml
```

## Run the presentation GUI

Tkinter is included with the installed Python 3.13 runtime, so the basic GUI needs no
additional package. Start the prepared professor demonstration from the repository root:

```powershell
python -m blackout gui
```

Or open another scenario explicitly:

```powershell
python -m blackout gui configs/broken_route.yaml
```

Use **Step Event** to explain the event queue one event at a time, or **Play** to animate
the complete deterministic trace. In the prepared presentation scenario:

1. The message starts at A and custody moves to B.
2. The B-C link fails before that transfer can complete, so B safely retains the message.
3. E moves into range at simulated time 6 and passes the Adaptive score threshold.
4. F appears at time 8 and becomes the next custodian.
5. F contacts destination D at time 10; delivery completes at time 11.

The right panel shows every event and the latest Adaptive decision, including normalized
connectivity (C), proximity (P), buffer availability (B), node state (S), total scores,
and the hysteresis threshold. Green lines are active contacts, dashed red lines are forced
failures, and the gold ring identifies the current message custodian.

Run the automated tests:

```powershell
python -m pytest
```

## Development principles

- Use simulated time rather than wall-clock time for experiments.
- Replay identical traces when comparing routing strategies.
- Keep routing copies separate from link-level retransmissions.
- Keep visualization independent from simulation decisions.
- Record random seeds and configuration with every experiment.
- Do not claim that Adaptive Routing always outperforms the baselines.
- Keep optional TCP/UDP and external-tool demonstrations separate from the core simulator.

## Current documents

- `BLACKOUT_ARCHITECTURE.md` - implementation architecture and experimental design
- `requirement.txt` - pinned runtime, analysis, testing, and quality dependencies
- `blackout/config.py` - strict Pydantic scenario schema and YAML loader
- `blackout/events.py` - typed events used across simulation components
- `blackout/simulation/engine.py` - deterministic simulated-time scheduler and trace
- `blackout/simulation/scenario.py` - initial scenario-to-event translation
- `blackout/simulation/runtime.py` - configured nodes, message lifecycle handlers, and snapshots
- `blackout/simulation/topology.py` - range contacts, movement reconciliation, and failures
- `blackout/routing/single_copy.py` - explainable greedy custody forwarding
- `blackout/routing/adaptive.py` - weighted Adaptive score, hysteresis, and cooldown
- `blackout/gui.py` - Tkinter presentation and event-trace interface
- `configs/presentation.yaml` - scripted successful alternate-route demonstration
- `blackout/models/message.py` - immutable message identity, TTL, hops, and lifecycle
- `blackout/models/buffer.py` - byte-capacity storage, duplicate checks, and expiry
- `blackout/models/node.py` - node position, state, contacts, counters, and local buffer
- `configs/default.yaml` - baseline six-node experiment configuration
- `configs/broken_route.yaml` - deterministic B-C failure acceptance scenario
- `tests/` - configuration, determinism, scheduling, and scenario timeline tests

## License

No license has been selected yet. Until one is added, normal copyright restrictions apply.
