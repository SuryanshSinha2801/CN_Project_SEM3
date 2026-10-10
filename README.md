# CN Project SEM3

BLACKOUT is a Python-based educational simulator for studying communication in intermittently connected and delay-tolerant networks. It demonstrates store-carry-forward delivery when links fail or a continuous source-to-destination path does not exist.

## Project status

The Python 3.13 MVP is implemented. It includes a deterministic event engine, dynamic
contacts and failures, finite buffers, Adaptive/Epidemic/Binary Spray-and-Wait routing,
Stop-and-Wait reliability with ACK loss and retries, a Tkinter presentation GUI, automated
metrics, CSV/JSON exports, and multi-seed policy comparison.

## Implemented capabilities

- Dynamic two-dimensional nodes and range-based contacts
- Node movement, link failures, packet loss, and temporary partitions
- Finite buffers and store-carry-forward delivery
- Epidemic Routing
- Binary Spray-and-Wait Routing
- Explainable BLACKOUT Adaptive Routing
- Acknowledgements, timeouts, and retransmissions
- Stop-and-Wait link reliability
- Reproducible scenario traces and random seeds
- Delivery, delay, hop, copy, overhead, buffer, and throughput metrics
- Tkinter visualization and CSV/JSON/SVG experiment reporting

CRC, message fragmentation, Sliding Window, adaptive retransmission timeouts, and a more
advanced Pygame view are optional extensions outside the completed MVP.

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

For an interactive run, type a message, choose different source and destination nodes,
leave **Automatic random failures** enabled, and click **Start Custom Message**, then
**Play**. The simulator breaks a seeded random live link, records the detection, retains
custody at the sender, and applies the routing policy to find an alternate contact. Use
**Break Random Link** to inject another three-second failure manually.

The full presentation narrative is in [PRESENTATION_GUIDE.md](PRESENTATION_GUIDE.md).

## Run experiments and export results

Run one configured policy and write its complete event trace and metric summary:

```powershell
python -m blackout run configs/presentation.yaml --output results/demo
```

Compare all three policies with identical scenarios and channel outcomes across seeds:

```powershell
python -m blackout experiment configs/presentation.yaml `
  --seeds 1 2 3 4 5 6 7 8 9 10 `
  --output results/comparison
```

The experiment produces `comparison.csv`, `delivery-comparison.svg`, and a `runs` folder
containing each run's event CSV and metrics JSON. Routing copies and link retransmissions
are deliberately reported as separate metrics.

## Docker package

Use [DOCKER.md](DOCKER.md) to build the Python 3.13 test image, run scenarios, preserve
result files, export the image as a `.tar`, verify its SHA-256 checksum, and load it on
another computer. The Docker image covers the engine and CLI; run Tkinter natively because
ordinary containers do not have a desktop display.

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
- `blackout/metrics.py` - delivery, delay, hops, overhead, throughput, and buffer metrics
- `blackout/experiments/` - single-run exports and fair multi-policy replay
- `blackout/gui.py` - Tkinter presentation and event-trace interface
- `PRESENTATION_GUIDE.md` - professor-demo script, architecture, algorithms, and viva notes
- `configs/presentation.yaml` - scripted successful alternate-route demonstration
- `blackout/models/message.py` - immutable message identity, TTL, hops, and lifecycle
- `blackout/models/buffer.py` - byte-capacity storage, duplicate checks, and expiry
- `blackout/models/node.py` - node position, state, contacts, counters, and local buffer
- `configs/default.yaml` - baseline six-node experiment configuration
- `configs/broken_route.yaml` - deterministic B-C failure acceptance scenario
- `tests/` - unit and integration coverage for configuration, routing, reliability, metrics,
  determinism, and the scripted timeline

## License

No license has been selected yet. Until one is added, normal copyright restrictions apply.
