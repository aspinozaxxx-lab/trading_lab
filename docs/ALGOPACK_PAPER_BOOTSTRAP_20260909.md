# Scheduled once-only paper bootstrap

2026-09-08. Operational units c760e2b pushed, exact three-file archive deployed and
systemd-analyze verify PASS; local/server2tests PASS (server0.02s UID999), Ruff/diff PASS.
These units execute the previously documented operator lifecycle, not new trading code.
They do not change the sealed100-file bundle, model/config or future boundary.

Installed only `trading-lab-paper-bootstrap-20260909.service/.timer` after exact-target
absence checks, no-clobber copy and byte comparison. Enabled/started ONLY the timer.
Actual systemd observation: ActiveState=active/SubState=waiting;
NextElapseUSecRealtime=Wed2026-09-09 00:01:00MSK; LastTriggerUSec empty.
Bootstrap service inactive/dead, ExecMainStartTimestamp empty. No initialization occurred.

At F+1minute, ordered oneshot steps:

1. Guard absent exact activation account root; existing/partial root skips automatic init.
2. Under trading-lab run actual runtime V2 --check with pinned activation SHA.
3. Under trading-lab run --initialize once. Failure aborts subsequent steps.
4. Copy sealed paper service template without overwrite; compare installed bytes exactly.
5. daemon-reload and start exact activation instance.

No bootstrap credential file, no early HTTP, no shell interpolation or account reset.
Restart=no; timer Persistent=false and exact once-only date. A missed/offline date does
not silently catch up. Failed/partial initialization or subsequent failure needs explicit
review. Root privilege is limited to operational unit installation/start; Python checks
and account initialization run UID999. Running paper service loads its existing env only
after start per sealed unit. No OS reboot persistence added to the paper service itself.

## Next observation

Poll the actual timer/service, not a presumed background job. Before due time expect
waiting and no service process. After due time inspect bootstrap Result/ExecMainStatus,
paper service state/main PID and activation-root metadata before source outcomes. First
calendar window September9 09:00–09:05Moscow must not be missed. On failure preserve
root/journals; never blindly rerun --initialize. Source/schema/timing admission still
requires actual future observations. Target20–50% annual income remains unverified.

To cancel only this scheduled startup: `systemctl disable --now
trading-lab-paper-bootstrap-20260909.timer`. Do not stop other collectors. This does not
stop an already running paper service or erase any evidence.
