# Policy source V2 — date-only footer, unchanged end-of-day availability

V1 after pre-source push72df00b passed12server tests and all listing/year coverage
checks. It stopped on the29th article,2022-07-22: catalogue13:30 versus footer00:00:00.
The original raw HTML is preserved, SHA2f0dfe1895d58a4d74164d2c54eb4b6cd8d9e6733d14a76558cbec44c1e2814d.
No processed manifest, signals, market outcomes or PnL were created.

V2 handles only this date-only representation. The date must still match both header
and catalogue. Retain the literal footer, set footer_time_known=false, separately store
the catalogue timestamp and use it as a publication-label proxy, NOT witnessed receipt.
Availability remains23:59:59Moscow on that same day, never midnight. Nonzero clock
disagreement, different date/headline, empty body or protected release still fail.
All V1 bounds, source selection, budgets and rights rules remain unchanged.

Source V1 files/output stay immutable; V2 has separate config/seal/output and a bounded
new acquisition. The adapter is process-local, restores the original parser and does
not overwrite frozen files. One full raw/hash/normalization replay follows collection.
Current-vintage/original-revision limitation remains; no economic admission. A separate
V72 dictionary/timing/execution/control/cost seal is required before market outcomes.
