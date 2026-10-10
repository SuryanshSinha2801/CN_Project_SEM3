# BLACKOUT Presentation Guide

## 1. Project in one sentence

BLACKOUT is a Python 3.13 discrete-event simulator that shows how a message can still
reach its destination in a disrupted network by being stored on a node, carried while
the topology changes, and forwarded when a useful contact appears.

## 2. Problem being solved

Ordinary routing assumes an end-to-end path exists. During a disaster, blackout, sparse
mobile network, or infrastructure failure, that assumption is false. BLACKOUT uses
Delay-Tolerant Networking (DTN): a node keeps the message in a finite local buffer when
no safe next hop exists instead of dropping it immediately.

## 3. Architecture

```text
YAML scenario
     |
     v
Configuration validation (Pydantic)
     |
     v
Deterministic event engine <---- GUI controls / observes
     |
     +--> topology and contacts
     +--> node buffers and message lifecycle
     +--> routing policy (Adaptive / Epidemic / Spray-and-Wait)
     +--> link reliability (packet, ACK, timeout, retry)
     |
     v
Immutable event trace --> metrics --> CSV / JSON / SVG
```

The GUI never makes routing decisions. It renders simulation snapshots, so animation
speed cannot change experimental results.

## 4. Routing algorithms

### BLACKOUT Adaptive

Adaptive is a single-copy custody policy. A candidate relay receives a weighted utility:

```text
U = 0.35C + 0.35P + 0.20B + 0.10S
```

- `C`: recent connectivity utility.
- `P`: normalized proximity to the destination.
- `B`: free-buffer fraction.
- `S`: node-state utility.

The copy moves only if the candidate improves the score by the configured hysteresis
threshold. A cooldown prevents immediate ping-pong forwarding. Every component and the
reason to forward or hold is placed in the event trace.

### Epidemic

Every useful contact receives a new logical copy unless it already holds that message.
This normally improves reachability, but consumes more bandwidth and buffer space.

### Binary Spray-and-Wait

The source begins with a finite copy budget. A node with more than one token gives half
its tokens and a new copy to a contact. A node with one token waits for the destination.
It limits overhead while retaining more opportunities than a single-copy policy.

## 5. Reliable link transfer

Each routing transfer uses Stop-and-Wait:

1. Sender emits a packet.
2. The deterministic channel decides whether the packet is received or lost.
3. A successful receiver emits an ACK.
4. If the ACK is lost, the sender times out and retries.
5. The routing transfer completes only after its ACK arrives.

The sender retains its message until acknowledgement, and the destination counts a
logical message only once. Packet retries are link behavior; Epidemic and Spray copies
are routing behavior, so the simulator records them separately.

## 6. Live demonstration

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m blackout gui
```

Suggested narration while pressing **Step Event**:

1. At time 0, message `demo` is created at A.
2. A transfers custody to B.
3. The B-C link fails before B can complete that route; B retains the message.
4. E moves into range and has enough Adaptive utility, so B forwards to E.
5. E forwards to F when that contact becomes useful.
6. F later reaches D and delivery completes at simulated time 11.

Green lines are active contacts, dashed red lines are forced failures, the gold ring is
the current custodian, and the right panel explains each event and Adaptive decision.

### Interactive message and random failure

1. Enter any message in the **Message** field.
2. Select different nodes under **Source** and **Destination**.
3. Keep **Automatic random failures** selected.
4. Click **Start Custom Message**, followed by **Play**.
5. Point out the red failed link and the immediate `transfer_failed` event. The sender
   keeps custody, and later `forward_decision` events explain the alternate route.
6. Use **Break Random Link** if you want to inject another temporary failure manually.

Random selection uses the scenario seed, so resetting and replaying the same inputs gives
the same failure. Short text is carried in a 1 KiB simulated application packet, while
longer text uses its actual UTF-8 byte length.

## 7. Reproducible comparison

```powershell
python -m blackout experiment configs/presentation.yaml `
  --seeds 1 2 3 4 5 6 7 8 9 10 `
  --output results/comparison
```

Open `results/comparison/delivery-comparison.svg` for the chart and
`results/comparison/comparison.csv` for the complete table. Each policy uses the same
scenario, seed, mobility, failures, and deterministic channel outcomes for a fair replay.

## 8. Metric definitions

- Delivery ratio: unique delivered messages divided by generated messages.
- Delay: delivery time minus creation time.
- Hop count: successful forwards before first delivery.
- Routing copies: replicas created by Epidemic or Spray-and-Wait.
- Link retransmissions: repeated Stop-and-Wait attempts after packet or ACK loss.
- Routing overhead: successful forwards beyond the minimum delivered count per delivery.
- Buffer utilization: time-weighted occupied fraction, plus peak fraction.
- Throughput: unique delivered payload bytes divided by simulated duration.

## 9. What is complete and what remains optional

The assessed MVP is complete: three routing policies, store-carry-forward, dynamic
contacts, link failures, finite buffers and TTL, packet/ACK loss, retransmissions,
metrics, exports, tests, and a presentation GUI all run on Python 3.13.

Good future extensions are multi-packet fragmentation with CRC, Sliding Window ARQ,
adaptive retransmission timeout, richer randomized mobility, confidence-interval plots,
and a Pygame renderer. These are enhancements, not hidden dependencies of the current
implementation.
