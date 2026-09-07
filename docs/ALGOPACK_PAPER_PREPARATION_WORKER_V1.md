# Isolated preparation worker V1

2026-09-08. New module, not yet connected to runtime ticks. F=null and full activation
absent. No actual source/model preparation process has been launched.

prepare uses fixed existing flow selection/import, packet capture and pinned predictor,
publishing source/selection/forecast references to market journal only. No account object,
reserve, fill or portfolio write. This is code-path separation, NOT an OS permission
sandbox: eventual worker runs under the same service UID. Checks activation closure,
exact slot and actual E+3..E+10 before work and between major phases; late capture never
starts inference. Predictor retains original completion masks. Failures keep immutable
source attempt and sanitized status; duplicate child source key blocks repeat work.

Supervisor reserves canonical scheduler preparation key before spawning fixed module
command with activation SHA and UTC slot. No token in command line/output. Child loads
server environment token only after activation/slot verification; creates its own HTTP
session with trust_env=false, never shares the parent's Session across processes.

One child at a time; start/poll never wait/communicate/join. Poll reaps actual exit code,
never admits a forecast merely because exit0. At E+10 request terminate; after5seconds
monotonic grace request kill while continuing nonblocking polls. Keep child handle until
exit is observed. Restart does not launch another child for an existing scheduler key.
Source/journal publication itself is synchronous: fsync/activation-check latency is NOT
proven bounded by these primitives. Spawn also has normal OS overhead.

## Integration requirements still open

Runtime currently still uses the original synchronous slot; do not claim its interference
defect is fixed by this module. New executor must poll supervisor while servicing due
positions, consume only fully observed timely forecast references, and split remaining
blocking calendar/mark/quote/decision work as well. Exit-first source work needs its own
bounded scheduling; four serial quotes can still exceed30seconds. Preserve one ledger
owner and original economic rules. Late/failed child evidence remains visible, not retry.
Service must use control-group lifecycle cleanup for child processes; no surviving orphan
may run alongside a replacement runtime. Do not implement a busy-wait or blocking join.

9tests: activation before credential, single child/nonblocking polls, terminate/kill,
success/failure without forecast admission or repeat, spawn failure retention, source-only
phase ordering, late capture prevents model call; one real benign sleeping subprocess
checks responsive polling/termination (test cleanup explicitly reaps it). Other child,
HTTP and model behavior is synthetic. Server verification recorded separately.
Next: integrate an asynchronous executor and retest the actual interference scenarios.
