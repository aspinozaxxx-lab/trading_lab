# Prospective paper service — prepared, not installed or started

2026-09-08. Template `deploy/systemd/trading-lab-algopack-paper@.service` runs only
runtime V2 on gpu-mlserver. Instance is the exact activation SHA-256, never a token.
Read-only server inspection: systemd255, trading-lab UID999/GID989, activation absent,
no matching paper --serve process. No collector environment contents were read.

The service checks the complete activation before --serve; it never initializes/reset
accounts. Root lifetime lock is still enforced by the runtime. No Install section,
timer, automatic restart or report-triggered stop: startup/recovery needs explicit
operator review. Restart=no preserves a visible failure rather than silently declaring
a failed interval healthy. A clean restart also never repeats canonical dispatches.

KillMode=control-group sends termination to the parent AND source/model children;
after15s systemd kills remaining processes. Python finally is only supplementary.
The service uses UID999, UMask0077, read-only system/code/models/witnessed input and
one writable activation root. PrivateTmp permits private temporary files, not arbitrary
data-root writes. The existing server-only EnvironmentFile is required; no credential
in instance, argv, repository or new file. Workers inherit the existing environment.

## Activation and operations sequence

1. Finish real-component synthetic timing/integration checks; this unit is not latency
   evidence. Include this template's bytes in the complete pre-F bundle, together with
   current runtime/worker/report closure. Config must select runtime V2.
2. Publish complete seal/models/activation and a genuinely future F. No source HTTP,
   production model read or historical2026 outcome inspection before admission.
3. After F, explicitly --check then --initialize once under trading-lab, outside the
   service. Existing/partial root is a recovery case, never an excuse to initialize again.
   The instance directory must exist before service mount namespace setup.
4. Copy only the pushed, SHA-verified template to /etc/systemd/system and daemon-reload.
   Start the exact activation instance explicitly; no enable command or boot timer here.
   Verify actual process/cgroup, Result and sanitized runtime output. Service sandbox
   compatibility and actual group cleanup remain runtime acceptance checks, not proven
   by static tests or systemd-analyze verify. Do not start production merely to test them.
5. During the prospective run, retain every missed decision/failed day. No automatic
   retries of canonical slots, no revised costs/thresholds after outcomes.

## Reporting cadence

The runtime publishes its daily snapshot at18:20–18:20:30 Moscow when maintenance is
safe. Do NOT stop it before this window completes. Economic report CLI owns the same
nonblocking lifetime lock and must run offline. A planned report can run after18:21
Moscow only after checking that stopping will not interrupt actionable positions or
workers; an unsafe stop is deferred, not a forced close. Stop the exact service and
verify it inactive with an empty cgroup before report execution. Preserve unresolved
risk and all missing snapshots; report output is not a repair of missing data.

Run the fixed report-store CLI with exact activation SHA and mature --through date;
the same date's canonical partial/complete report must not be retried or overwritten.
After a successful report or a reviewed report failure, restart the same service with
unchanged activation well before next09:00 Moscow calendar window. Record downtime.
No automated reporting timer is installed: crash recovery, runtime health and reporting
handoff need integrated validation first. Short-run reports cannot prove20–50%/year.
