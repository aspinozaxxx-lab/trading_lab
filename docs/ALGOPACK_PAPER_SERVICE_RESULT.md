# Paper service template verification

2026-09-08. Pushed ad371f3 before exact three-file archive transfer. Extracted with
tar --keep-old-files to /opt/trading_lab only; no /etc/systemd/system installation,
daemon-reload, start, enable or actual worker invocation.

Server systemd255 `systemd-analyze verify` returned0. Under trading-lab UID999,
service static contract + runtime V2 tests:14PASS1.37s, process exit0. Synthetic test
roots `/tmp/algopack_paper_service_ad371f3_tests` and `_cache`. Local3service +2encoding
tests PASS; Ruff and diff checks PASS. Tests do not launch this unit or prove sandbox
compatibility, actual cgroup cleanup or timing under real workloads.

Local/server exact SHA-256:

| File | SHA-256 |
| --- | --- |
| trading-lab-algopack-paper@.service | c51097f002b3bf939add09ef69233076b5d94269b3e10002fec917f1ec4c3609 |
| test_algopack_paper_service.py | 262f82b0cfe1c7dade9b81d59f4ca4621a9fe4de527b9b685ba6740b44d87ec2 |
| ALGOPACK_PAPER_SERVICE.md | 3406cb315bbe2df23297fd388e03f35449ffd9df2e504f5e9a26dd618f5afa59 |

Post-check: system unit path and production activation file absent. Frozen parent code
was not touched. No prices, models, source HTTP, economic results or credential contents
read. F remains null. Next full-component synthetic performance/sandbox verification,
then full pre-F seal/publication; this result is infrastructure evidence, not profit.
