"""Source-observed commands into an anchored paper ledger; no network or broker orders."""

from pathlib import Path

from market_lab.futures import algopack_paper_portfolio_anchor_v1 as anchors
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE

portfolio, journal = anchors.portfolio, anchors.journal
source, execution = portfolio.source, portfolio.execution
PROTOCOL = "algopack_paper_execution_bridge_v1"


def ready(activation):
    anchors.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_execution_bridge_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("execution bridge absent from complete activation")


class ExecutionBridge:
    """Only references cross this boundary, never caller-supplied prices, intent or Fill.

    Source observation and clock are actual now. Ledger reducer remains the final
    aggregate risk/duplicate gate; caller must preserve failed decisions separately.
    """

    def __init__(self, account: anchors.AnchoredPortfolio, market_root: Path):
        ready(account.activation)
        if not isinstance(account, anchors.AnchoredPortfolio):
            raise ValueError("anchored account required")
        journal._ordinary(market_root, directory=True)
        if market_root in (account.control, account.ledger):
            raise ValueError("source and account roots must be distinct")
        self.account, self.market_root = account, market_root

    def _state(self):
        ready(self.account.activation)
        return self.account.snapshot()

    def _quote(self, reference):
        observation = source.observe(self.market_root, reference, self.account.activation)
        return observation, source.quote_inputs(observation)

    def _append(self, operation, data, observations):
        state, ref = self.account.append(
            operation=operation,
            data=dict(
                **data,
                execution_evidence=dict(
                    protocol_id=PROTOCOL,
                    market_root=str(self.market_root),
                    observations=observations,
                    checked_at=journal.now().isoformat(),
                    execution_admitted=False,
                ),
            ),
        )
        return dict(
            status="RECORDED",
            operation=operation,
            record=ref,
            sequence=state["sequence"],
            execution_admitted=False,
        )

    def reserve(self, *, asset, arm, forecast_reference, quote_reference, calendar_reference):
        state = self._state()
        consumed = journal.consume_forecast(
            self.market_root, forecast_reference, self.account.activation.future_start
        )
        quote_observation, inputs = self._quote(quote_reference)
        if inputs is None:
            return dict(status="UNAVAILABLE_QUOTE", execution_admitted=False)
        quote, terms = inputs
        calendar = source.observe(self.market_root, calendar_reference, self.account.activation)
        candidate = consumed["payload"]
        session = source.session_input(
            calendar,
            secid=quote.secid,
            entry_at=source._stamp(candidate["planned_entry_at"]),
            exit_at=source._stamp(candidate["target_exit_at"]),
        )
        if session is None:
            return dict(status="NO_UNINTERRUPTED_SESSION", execution_admitted=False)
        at = journal.now()
        valuation = portfolio.view(state, arm, at)
        if valuation["status"] != "VALUED" or valuation["equity_rub"]["1x"] <= 0:
            return dict(status="UNRESOLVED_OR_EXHAUSTED_ACCOUNT", execution_admitted=False)
        occupied = tuple(
            row["intent"]["asset"]
            for row in state["positions"].values()
            if row["intent"]["arm"] == arm
        )
        status, intent = execution.make_intent(
            consumed=consumed,
            asset=asset,
            arm=arm,
            quote=quote,
            terms=terms,
            session=session,
            equity_rub=valuation["equity_rub"]["1x"],
            free_margin_rub=valuation["free_margin_rub"],
            open_assets=occupied,
            unresolved_positions=False,
            at=at,
        )
        if intent is None:
            return dict(status=status, execution_admitted=False)
        forecast_observation = {
            key: consumed[key] for key in ("kind", "key", "record_sha256", "observed_at")
        }
        return self._append(
            "RESERVE",
            dict(intent=intent),
            [
                forecast_observation,
                quote_observation["source_observation"],
                calendar["source_observation"],
            ],
        )

    def fill_due(self, *, position, quote_reference=None):
        state = self._state()
        row = state["positions"][position]
        if row["status"] == "UNRESOLVED":
            return dict(status="UNRESOLVED_POSITION_RETAINED", execution_admitted=False)
        intent = portfolio.decode(execution.Intent, row["intent"])
        is_exit = row["entry"] is not None
        due = intent.exit_at if is_exit else intent.entry_at
        at = journal.now()
        if at < due:
            return dict(status="NOT_DUE", execution_admitted=False)
        if at > due + execution.MAX_FILL_DELAY:
            return self._append(
                "UNRESOLVED" if is_exit else "CANCEL",
                dict(
                    position=position,
                    reason="MISSED_EXIT_WINDOW" if is_exit else "MISSED_ENTRY_WINDOW",
                ),
                [],
            )
        if quote_reference is None:
            return dict(status="AWAITING_POST_BOUNDARY_QUOTE", execution_admitted=False)
        observation, inputs = self._quote(quote_reference)
        if inputs is None:
            return dict(status="UNAVAILABLE_QUOTE", execution_admitted=False)
        status, fill = execution.simulate_fill(
            intent,
            is_exit=is_exit,
            quote=inputs[0],
            terms=inputs[1],
            intent_durable_at=source._stamp(row["intent_durable_at"]),
            at=journal.now(),
            future_start=self.account.activation.future_start,
        )
        if fill is None:
            return dict(status=status, execution_admitted=False)
        return self._append(
            "EXIT" if is_exit else "ENTRY",
            dict(position=position, fill=fill),
            [observation["source_observation"]],
        )
