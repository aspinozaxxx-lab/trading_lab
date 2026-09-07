# Source-bound portfolio mark refresh V1

2026-09-07. Integration-only, no new strategy/outcomes. Код
`src/market_lab/futures/algopack_paper_mark_refresh_v1.py`.
Complete activation обязана содержать SHA модуля и неизменённые parents. F=null.

`refresh(ExecutionBridge, references)` получает только source references по ключам
текущих открытых позиций. Pending reservations не требуют цены для резервирования;
foreign/pending reference keys отклоняются до записи. Для каждой открытой позиции
execution_source.observe выполняет raw replay и actual observation; quote_inputs
строит датированные Quote/Terms. Пустой, непригодный или непрочитанный источник даёт
explicit None mark; previous successful marks никогда не подставляются.

Весь набор marks записывается одной anchored MARK операцией. Evidence хранит protocol,
root, actual checked_at, observation refs и source statuses. Ошибки чтения/схемы/целостности
помечаются SOURCE_REPLAY_FAILED, без текста исключения, секретов и произвольных payload.
Это не разрешение тихо объявить успешным повреждённый источник: equity остаётся unknown.
Статус OBSERVED_CANDIDATE означает только parsed source, не пригодную ликвидационную цену.

После durable publication заново читаются фактические часы и parent portfolio.view
рассчитывает оба arm/оба cost scenarios: identity/date/freshness/contract-conversion/
exit-depth/fees gates остаются действующими. Если котировка устарела за время записи,
итоговая equity неизвестна, даже если до записи была свежей. Нет backdating.

Liquidation MTM учитывает вход и условное закрытие; это не закрытая сделка и не
реализованный cash. Новая цена не снимает UNRESOLVED_POSITION после missed exit.
Другой независимый arm оценивается отдельно. Pending notional/margin сохраняются.

## Границы

Возвращаемый OBSERVED_PORTFOLIO_NOT_DAILY_SNAPSHOT — оперативное состояние с ledger
reference и actual observed_at. Это ещё не scheduled daily evaluation snapshot:
нет complete calendar/decision denominator, daily publication и offline evidence audit.
Не считать CAGR или подтверждённую доходность непосредственно по этим вызовам.
Нет HTTP, retry, broker order, fit, retrospective PnL или actual market observations.

8 synthetic tests: activation refusal, cost-adjusted MTM/restart, missing/unavailable/
corrupt source replacement, publication delay expiry, unresolved exit retention,
pending budget/foreign reference. Linux fixture использует реальный anchored journal,
source projection stubbed; actual raw replay отдельно покрыт parent source suite.
