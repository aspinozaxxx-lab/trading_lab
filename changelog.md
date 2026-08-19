# Changelog

## 0.6.0 - 2026-08-19

- Kod, konfiguracii i testy pereneseny v GitHub-repozitorii `trading_lab`.
- Dannye, run-artefakty, modeli i checkpoints vyneseny za predely Git v `D:\Projects\trading_lab_data`.
- Dobavleny `AGENTS.md` i dokumentaciya tekushchego sostoyaniya, arhitektury, dannyh i runbook.
- V9 structural breadth dal luchshii research-proxy CAGR 6.77 procenta, Sharpe 0.784 i 5.35 procenta CAGR pri 2x costs, no exact-execution ostalsya fail-closed iz-za istoricheskih specs i settlement gaps.
- Event key-rate ostavlen tol'ko kak malovyborknyi research lead: 10 sdelok, CAGR 0.99 procenta, Sharpe 0.82.
- Corridor, continuous 10m timing, event-timing overlay i 30-stock market graph poluchili yavnyi NO-GO.
- Relative momentum imel polozhitelnyi IC, no long-only realizaciya dala Sharpe 0.18 i MDD okolo 49 procentov, poetomu tozhe otklonena.
- Razrabotka po-prezhnemu zapreshchaet chtenie rynochnyh dannyh 2026 goda; ni odin V9 rezultat ne yavlyaetsya live-ready.

## 0.5.0 - 2026-08-18

- Dobavlen development-only daily residual-TCN po original30 s 66 causal priznakami i kontekstom IMOEX/RVI/RGBI/CNYRUB_TOM.
- Na izolirovannom RTX 5090 obucheny 20 modelei: chetyre expanding outer-fold i pyat zafiksirovannyh seed bez seed-selection.
- Daily target i backtest ispol'zuyut next-session exact open i pervyi factual open ne ran'she planovogo pyatidnevnogo vyhoda.
- Rolling beta privedena k soglasovannym open-to-open intervalam; evaluation ne filtruyet resheniya po budushchemu target.
- Realizovan event-driven dvizhok pyati sleeves s cash/quantities, netting orderov, izderzhkami, borrow, carry missing exit i fail-closed execution status.
- Neizvestnaya participation, missing entry i nedostupnyi rebalance bol'she ne mogut dat' lozhnyi complete-status.
- Protocol i exact runtime-config zapechatany otdel'nymi SHA-256 i semanticheski sveriayutsya do chteniya development-dannyh.
- Exact diagnostic run dal minus 2.226 procenta CAGR, Sharpe minus 0.148 i 28.988 procenta max drawdown; 50-procentnyi stretch gate ne proiden.
- Frozen asset-holdout iz 19 novyh instrumentov ostalsya neotkrytym; status zafiksirovan kak NO_GO_FOR_LIVE_TRADING.
- Fixed probe iz 15 long-only pravil dal luchshii aggregate CAGR 7.006 procenta i 5.847 procenta pri 2x costs, no tol'ko dva iz chetyreh fold byli polozhitel'nymi.
- Causal daily-panel iz 62190 strok i 102 kolonok sohranen v lokal'nyi Parquet-kesh s proverennym SHA-256.
- Lokal'nye proverki rasshireny do 84 passed i 1 skipped bez optional Torch; na servere 43 sequence-proverki prohodyat s Torch 2.13/CUDA.

## 0.4.0 - 2026-08-17

- Dobavlen causal 10-minute TCN po 30 TQBR-instrumentam i bolee chem pyati millionam barov 2018-2026.
- Sozdano izolirovannoe server-okruzhenie Python 3.11.4 s Torch 2.13/CUDA 13 na RTX 5090.
- Realizovany sequence-store, temporal purge, grouped cross-sectional ranking loss i event-driven intraday backtest.
- Ustraneny future-target availability look-ahead, neravnyi wall-clock horizon i zanizhenie pervoi prosadki.
- Sequence v2 ne proshel development/asset checks i poluchil NO_GO status bez obeshchaniya dohodnosti.

## 0.3.0 - 2026-08-17

- Chasovoi TQBR-universum rasshiren do 16 akcii i bolee chem 498 tysyach lokal'no zakeshirovannyh barov.
- Dobavleny otdel'nye development i instrument-holdout universumy s selection seal do chteniya testovyh cen.
- Realizovan dnevnoi cross-sectional panel s ispolneniem signala tol'ko na sleduyushchem open.
- Dobavlen XGBoost Ranker 3.2.0 s CUDA, kvartal'nym expanding walk-forward i dvuhdnevnym embargo.
- GPU-ranker obuchaetsya na 32 istoricheskih i cross-sectional priznakah bez ticker-identity.
- Dobavleny redkii rebalance, absolutnyi momentum, risk-off, inverse-volatility vesa i tri scenariya plecha.
- Validation 2023-2025 dala 34.419 procenta CAGR dlya core i 54.356 procenta dlya risk-scenariya 2x.
- Novyi holdout 2026 dal otricatel'nye 15.836 procenta CAGR dlya core, poetomu sozdan yavnyi NO-GO artefakt.
- Doctor teper' pokazyvaet NVIDIA GPU, VRAM, draiver i versiyu XGBoost.
- Dobavleny komandy alpha i ranker, stress-artefakty, arhitektura modeli i feature importance.
- Nabor proverok rasshiren do 39 prohodyashchih testov; ruff ne nahodit narushenii.

## 0.2.0 - 2026-08-17

- Razobrany otricatelnye rezultaty pervogo ML-run i chrezmernaya zavisimost ot odnogo validation-perioda.
- Istoriya SBER rasshirena do 2015-2026 godov, a validation uvelichena do vosmi expanding fold.
- Dobavleny medlennyi ML/trend-hybrid i stateful robust-trend s razdelnymi porogami vhoda i vyhoda.
- Selection-gate dopolnen ogranicheniem oborota, stabilnostyu po fold i bezopasnym perehodom v cash.
- Vybor kandidata fizicheski fiksiruetsya do rascheta test-metrik v selected_strategy.json i run.log.
- V otchety dobavleny fold-diagnostika i yavnyi status post-selection-exploratory dlya uzhe prosmotrennogo perioda.
- Polozhitelnyi issledovatelskii run robust-trend dal 2.102395 procenta posle izderzhek na 2026 YTD.
- Rasshireny unit i skvoznye proverki; finalnyi nabor soderzhit 33 prohodyashchih testa.

## 0.1.0 - 2026-08-17

- Sozdan pervyi rabochii MVP lokalnoi laboratorii torgovyh strategii.
- Dobavleny MOEX ISS, lokalnyi fixture, Parquet-kesh i proverka shemy OHLCV.
- Realizovany buy-and-hold, SMA crossover i Logistic Regression.
- Dobavlen backtest s ispolneniem na sleduyushchem open, komissiei i proskalzyvaniem.
- Realizovany hronologicheskii split, gap, expanding walk-forward i netronutyi test.
- Dobavleno deterministichnoe Optuna-issledovanie s tablicei vseh trials i prichinami oshibok.
- Dobavleny CLI-komandy doctor, download, run, optimize i demo s offline-rezhimom.
- Realizovano sohranenie konfiguracii, metrik, leaderboard, sdelok, modeli, grafika i loga.
- Dobavleny avtomaticheskie testy izderzhek, metrik, look-ahead, splitov i skvoznogo CLI.
- Podtverzhdeny offline i online demo-zapuski na Python 3.11 v lokalnom okruzhenii.
