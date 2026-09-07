# Single-attempt forecast slot runner V1

2026-09-08. `src/market_lab/futures/algopack_paper_slot_runner_v1.py`.
Integration, no strategy tuning. Full activation plus own module SHA required; F=null.

For one fixed E-slot the caller may invoke run only E+3min≤actual now<E+10min.
Under a dedicated Linux attempt-root lock it records STARTED before work, then:
capture_packet → predict_slot with supplied witnessed flow reference (or explicit
missing None) → actual consume_forecast event → calendar → fresh open-position marks
→ one quote/asset and reserve decisions in fixed BR/MIX/RI/SI × fixed model order.
Each decision has STARTED and FINISHED records; terminal slot COMPLETE has8outcomes.
No caller-provided prices or model parameters; child gates and actual clocks remain.

Any existing STARTED directory, even partial, suppresses automatic re-execution.
Unknown lost acknowledgment never retries reservation. Failed phase is durably
recorded without exception/payload/token text. If failure publication also fails,
exception propagates and reserved attempt remains for inspection. Existing attempt
does not mean successful completion; partial/failed coverage must remain explicit.
Parent anchored ledger recovers committed operations; runner does not undo them.

Token is supplied in memory by future authorized server bootstrap, never read/logged
here. All HTTP paths stay behind complete activation and frozen transport checks.
Calendar/quote admission remains strict; late forecast cannot trigger late intents.
No broker orders; reservation is not entry fill or profit.

## Not yet complete runtime

No CLI/systemd unit, autonomous due-entry/exit pump, latest witnessed-flow selector,
official-day calendar/evaluation wiring or offline economic audit in this file.
Caller must schedule these and daily snapshots separately before complete activation.
Flow reference selection must be fixed as-of source availability, not chosen by PnL.
Errors can stop remaining decisions; forecast publication coverage does not prove
all8runtime decisions finished. Consumption/attempt journal provides evidence for
the forthcoming full runtime/economic review, not automatic admission by itself.

7synthetic tests: no activation, eight ordered decisions and duplicate suppression,
capture/predict/calendar errors without leaked text, lost decision acknowledgment,
outside-window refusal. Linux lock/journal real, child calls stubbed: this suite
tests orchestration, not actual HTTP/schema/model economics or profitability.
