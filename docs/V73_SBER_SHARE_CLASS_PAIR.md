# V73 — same-expiry SBER/SBERP pair, дешёвый event screen

Новый экономический механизм: временное расхождение цен двух классов акций одного
эмитента через фьючерсы с одинаковой датой исполнения. Это не выбор пары по корреляции,
не спред разных сроков, RI/MIX currency identity или V35 thirty-stock residual basket.
Исходная пара определена до цен и её результаты не использовались для выбора.

Архивный [отчёт Сбера за2015](https://fs.moex.com/content/annualreports/1998/2/sberbank-angl.pdf),
PDF page116 zero-based, печатные230–231, подтверждает намерение платить одинаковые
дивиденды на ordinary/preferred shares. Страница извлечена и визуально проверена по
PDF-навыку. Это лишь pre-period мотивация общей cashflow-связи, не конвертируемость,
не обязательство равных будущих выплат и не паритет цен. Voting/liquidity premia могут
быть устойчивыми. Сигнал использует собственное прошлое соотношение, не цену1:1.

## Правило до outcomes

В первую фактическую сессию недели в15:50Moscow выбирается ближайшая listed пара
одинакового expiration с DTE>=21calendar day. 12пар2023–2025,100shares/contract, все
из уже audited broad futures10m source. При missing выбранной пары нет fallback.
Source — close завершённого15:40 бара обеих ног; known positive volume/availability.
Log(common/preferred) сравнивается с median20строго прошлых совместных наблюдений этих
же контрактов внутри63calendar days, scale1.4826*MAD. При |z|>=2 long дешёвая относительно
своей истории нога, short дорогая; zero scale/недостаточная история/current missing flat.
Никакого fit, grid, выбора акции/срока по future return или новой инфраструктуры.

Вход на следующей фактической сессии15:50open, выход через5последующих сессий, те же
контракты. Все6ежедневных15:50 наблюдений обеих ног должны быть известны и активны;
иначе выбранный случай остаётся unresolved. Один common + один preferred contract,
направления противоположны. Нормировка результата — сумма начальных quoted notionals,
не margin и не весь капитал. Costs5/10bps per side на входные и выходные notionals.
Контроль на тех же событиях всегда long preferred / short common. Его не продвигать
постфактум. One-contract1% participation сохраняется отдельной diagnostic, не BBO proof.

Это предварительная event-проверка. Портфельные CAGR/Sharpe/MDD=null, overlap не суммируется
и не компаундится. PASS требует>=30complete events,0unresolved, положительные mean и
median primary net в обоих costs, положительное среднее каждого2023/2024/2025 и обгон
контроля в обоих costs. Только затем полный portfolio ledger/robustness/execution/demo.
Цель20–50% этим gate не заменяется. Нет пригодного эффекта — нет разработки нового engine.

## Входы и сохранение

Config `v73_sber_share_class_pair_v1.json` фиксирует source/PDF hashes; seal включает
code/tests/doc и V64 transitive helper identity до market outcomes. Source manifest
58581f7630c50c4173653473911165a0401e836611c3047800ccd4d65fe1fb62, 339metadata contracts,
2132435candles; min2023-01-03,max2025-12-18. До design читались только hashes/schema/dates,
spec metadata и исторический текст политики; prices/outcomes ещё не открывались.
На сервере исходного bundle не было: unchanged full bundle перенесён из внешнего
локального хранилища, без перезаписи/пересборки или новой market acquisition.

Canonical `/srv/trading_lab_data/runs/v73_sber_share_class_pair_v1_<seal12>` создаётся
один раз, хранит inputs/weekly decisions/events/metrics/identity. Отдельный read-only
replay сверяет selected events до endpoints и все метрики. Для нового run/sign/threshold
после результата разрешения нет. Protected2026/old paper/collectors/live остаются без изменений.
