# SimRT Linux TCP / UDP Library

Run `installSimRTARKLibrary` and select `SimRT / TCP UDP` in the Library Browser.
`setupSimRTNetworkLibrary` and `simrt_network_library` remain available for direct
library access and existing model links.
The library contains exactly three blocks: **TCP Setup**, **TCP Sent**, and
**TCP Receive**. Set `Protocol` on Setup to `TCP` or `UDP`; the send/receive
blocks use the matching `Channel`. No Instrument Control Toolbox is required.

## Endpoint Configuration

Use exactly one Setup per Channel (1 to 16). Setup owns its endpoint until
model termination. Duplicate Setup instances report -2 and cannot close the
original owner's sockets. Setup has one `int32 Status` output.

| Parameter | Meaning |
| --- | --- |
| Protocol | TCP or UDP |
| Role | TCP Client or Server; ignored for UDP |
| LocalAddress | Dotted IPv4 address to bind; `0.0.0.0` binds all interfaces |
| LocalPort | 0 chooses an ephemeral port; TCP Server requires 1 to 65535 |
| RemoteAddress | Numeric IPv4 destination; no DNS lookup |
| RemotePort | Destination port, 1 to 65535; ignored for TCP Server |
| SampleTime | Setup status polling period in seconds, default 0.001 |

TCP Server accepts one client at a time. TCP Client retries connections after
failure; servers accept another client after disconnect. Client attempts have
an approximately five second timeout and a 250 ms retry delay. UDP sends to
the configured destination and receives datagrams from any sender on its bound
local endpoint. A unicast network is assumed; broadcast, multicast, IPv6,
TLS, and application message framing are not provided.

## Ports

**TCP Sent** inputs are fixed-size `uint8 Data` (row or column, 1 to 4096
bytes), scalar `uint16 Length`, and scalar `logical Enable`. Only the first
Length bytes are queued. A zero or oversized Length returns -1 on every
enabled step. Disabled sends return 0 and enqueue nothing. `Status == 0`
means accepted by the local transmit queue, not acknowledged by the peer.

**TCP Receive** outputs are a fixed `BufferSize`-by-1 `uint8 Data` vector,
scalar `uint16 Length`, `logical Valid`, and `int32 Status`. BufferSize is
1 to 4096 (default 1024); SampleTime defaults to 0.001 seconds. Unused bytes
are zero. Valid=false means no packet/chunk was returned on this step.

TCP is a byte stream: one send can produce multiple Receive outputs, and
multiple sends can be coalesced. The application must supply its own framing.
A receive buffer smaller than an available TCP chunk preserves the remaining
bytes for subsequent steps. UDP preserves one datagram per output; an output
buffer smaller than the datagram returns a prefix with status -9 and discards
the remainder. Datagrams larger than 4096 bytes are discarded with status -9.
Zero-length received UDP datagrams have Valid=true and Length=0.

## Status Codes

| Code | Meaning |
| --- | --- |
| 0 | Ready / successful operation (Receive can still have Valid=false) |
| 1 | TCP waiting for a peer / asynchronous endpoint setup |
| 2 | Queue mutex busy; this step did not wait, retry on a later step |
| -1 | Invalid parameter, buffer, or transmit length |
| -2 | Duplicate Setup for this Channel |
| -3 | Channel is not configured, or Setup token is stale |
| -4 | Socket creation/configuration/listen failure |
| -5 | Bind failure (address unavailable or port already in use) |
| -6 | TCP connection refused, failed, or timed out |
| -7 | Queue full; send rejected or incoming UDP datagram dropped |
| -8 | Transport failure/disconnect; pending outbound bytes discarded |
| -9 | UDP datagram truncated/discarded |
| -10 | Worker thread creation failed |
| -11 | Host simulation transport disabled |

Setup reports current endpoint state. Receive also reports the latest pending
asynchronous fault once; repeated faults can coalesce. A fault and Valid=true
can occur together when previously received bytes are still queued. Receive
data retained across TCP disconnection remains in FIFO order. On disconnect,
queued and partially transmitted outbound bytes are discarded because peer
delivery cannot be established. Applications requiring delivery guarantees
must use framing, acknowledgments, and retry identifiers.

## Execution and Build

Each configured endpoint owns an ordinary `SCHED_OTHER` background thread.
Only the worker calls sockets; they are nonblocking, and connection readiness
uses a zero-timeout poll. The model's step functions only try-lock a mutex and
copy bounded buffers. There are no waits, allocations, DNS, or socket calls in
the step functions. Setup/release may create/join threads and must remain model
initialization/termination operations. Reconfiguration during stepping is not
supported. Model blocks sharing a Channel must use the same task or have
explicit model-level scheduling; a busy status is never silently retried in
the real-time task.

Each direction has 64 queue entries of up to 4096 bytes. Runtime storage is
static (approximately 8.4 MiB for 16 channels). TCP receive queue pressure
applies socket backpressure; UDP pressure drops the incoming datagram and
reports -7. Workers sleep approximately 1 ms between batches; these blocks
do not promise network transfer completion within the model's sample period.

`simrtlinux.net.Native` registers the C source/header and `-lpthread` with the
existing target packaging/build pipeline. Generated Linux deployment performs
real socket communication. Interpreted MATLAB/normal Simulink simulation
returns -11 explicitly and does not open sockets. The C runtime has a Winsock
compatibility branch solely for offline socket tests on this Windows workspace.

## Verification

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/drivers/network/run_offline_tests.ps1
```

The harness performs actual localhost TCP/UDP exchanges, checks byte stream
handling with seven-byte Receive buffers, UDP truncation, TCP reconnect,
duplicate and stale ownership, queue bounds, and nonblocking contention.
It also cross-compiles and links the Linux runtime with strict warnings.
Results are written to `tests/validation/network_runtime/network_runtime_tests.json`.

MATLAB interface checks:

```matlab
addpath('toolchain/simrt_linux_target');
results = runtests('tests/toolchain/tSimRTNetworkObjects.m');
assertSuccess(results);
```

These checks do not establish ARK2120 timing, Linux kernel behavior under load,
packet-loss behavior across a real network, or end-to-end hardware acceptance.
