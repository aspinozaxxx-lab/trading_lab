# Benign systemd sandbox and child cleanup verification

2026-09-08. Test dbf2bfc pushed before exact deployment. Explicit opt-in root pytest
created a uniquely named transient service using properties from the pushed paper unit.
Production EnvironmentFile, activation/check/serve commands were excluded; ReadWritePaths
pointed only to a new synthetic directory. Added RuntimeMaxSec30s safety backstop.
No production unit installed or started, no real token/environment file/model/market IO.

Probe ran as UID999 with actual production Python and imported runtime V2 successfully.
Actual ProtectSystem=strict blocked writing outside the allowed directory; inside file
mode was0600. Parent and child shared the exact service cgroup. Child explicitly ignored
SIGTERM after a readiness handshake. systemctl stop completed in15.085368s; both PID
paths absent, cgroup absent or empty. Result=timeout/ActiveState=failed/SubState=failed
is EXPECTED for the deliberately stubborn child, not successful graceful shutdown.
Whole-group SIGKILL cleanup verified. Test1PASS15.68s, terminal exit0.

Unit `trading-lab-synthetic-sandbox-850eea19b6ef4898a0e99da5108464bd.service` was stopped
in finally and its expected failed state subsequently reset, only for this exact test
unit. Synthetic evidence retained at `/srv/trading_lab_data/runs/paper-sandbox-xng7a50w`.
No directories deleted. Pytest temp/cache `/tmp/paper_systemd_sandbox_v1_tests` and
`_cache`. Post-check production activation and installed paper-service paths absent.

Scope limits: this verifies selected production sandbox properties with benign imported
code and subprocesses, NOT actual source TLS/entitlement/schema, production model loading,
full activated runtime, network timing or income. API environment is intentionally absent.
Future complete bundle must still include unit/code/config/model identities before F.

Next: assemble/check complete pre-F closure and publication prerequisites. F remains null;
no economic result or claim of20–50% income. Existing trained models and parent seals
are unchanged; do not repeat training or retrospective outcomes.
