# AnalystTeam — Milestones

## System Overview

4-layer architecture:
```
Data Sources → Analysts (unified template) → Master Analyst → RH Gateway + Monitor Agent
```

All analysts share one template (`BaseAnalyst`). All emit one schema (`TradeSignal`).
The system learns over time through the Memory Journal and RL loop in the Master Analyst.

---

## Phase 0 — Foundation `[CURRENT]`
**Goal:** Project skeleton that compiles and tests pass. Nothing trades yet.
**Duration:** Week 1–2

### M0.1 — Project structure & config
- [x] Repo layout: `core/`, `analysts/`, `master/`, `gateway/`, `configs/`, `tests/`, `scripts/`, `shared/`
- [x] `pyproject.toml` (Python 3.12, dependencies, tool config)
- [x] `.env.example` (all required env vars documented)
- [x] `Makefile` (up, down, test, lint, format)
- [x] `docker-compose.yml` skeleton (redis, app)

### M0.2 — Core schemas (the single source of truth) ✅
- [x] `core/schemas.py` — `Evidence`, `ExitRules`, `TradeSignal`, `OptionContract`
- [x] Pydantic v2 frozen models, all floats validated (int-vs-float legacy bug prevented)
- [x] `make_client_order_id()` — deterministic SHA-256 for idempotency
- [x] `computed_field` for OptionContract derived prices (Pydantic v2 frozen model compat)

### M0.3 — BaseAnalyst template ✅
- [x] `core/base_analyst.py` — wake triggers (SCHEDULE / DISCORD_EVENT / MARKET_EVENT)
- [x] Heartbeat started FIRST (asyncio.create_task before any other work)
- [x] Kill switch checked at every wake cycle before any data fetch
- [x] In-process dedup (5-min window per analyst+symbol+expiry+direction)
- [x] All rejections journaled — nothing silently dropped

### M0.4 — Infrastructure primitives ✅
- [x] `core/kill_switch.py` — safe-fail (missing file = BLOCKED, malformed JSON = BLOCKED)
- [x] `core/redis_client.py` — singleton, heartbeat loop, idempotency cache (24h TTL)
- [x] `core/file_writer.py` — always `tempfile.mkstemp()`, never `.tmp` suffix
- [x] `core/sanitizer.py` — Unicode zero-width strip, 12+ prompt injection patterns
- [x] `core/logging.py` — JSON structured logging, JSONL trade event journal
- [x] `core/market_data.py` — `MarketDataService` (yfinance MultiIndex flatten built in)

### M0.5 — Unit tests: 56/56 passing ✅
- [x] Schemas: frozen, int-vs-float guards, per-share vs per-contract correctness
- [x] Kill switch: missing → blocked, malformed → blocked, legacy field compat
- [x] File writer: concurrent writes don't corrupt (mkstemp proven), atomic confirmed
- [x] Sanitizer: zero-width stripping, 8 injection patterns blocked, URL soft-flag

---

## Phase 1 — Discord Layer + Vinod Analyst
**Goal:** End-to-end: Discord message → TradeSignal → paper order → monitor watches it.
**Duration:** Week 3–4

### M1.1 — Discord Gateway ✅
- [x] `analysts/discord/gateway.py` — single WebSocket, all channels, one process
- [x] History replay on `on_ready`: fetch last 50 msgs per channel, re-deliver if < 30 min old
- [x] Unicode strip before any parsing (sanitizer called in gateway)
- [x] Bot-message filter (is_bot field on each payload)
- [x] Dispatches to analyst queues by `channel_id`

### M1.2 — Vinod Analyst ✅
- [x] `analysts/discord/vinod.py` — VinodSPXAnalyst + VinodOtherAnalyst
- [x] SPX-only filter: accept SPX, ignore ES and option flies/condors/strangles
- [x] Buy buffer: execution_buffer_pct=0.20 → limit = signal_price × 1.20
- [x] Entry max: entry_buffer_pct=0.30 → reject if 30% above Vinod's price
- [x] First-sell exit: FIRST_SELL_FROM_SOURCE on SPX channel
- [x] Other: PARTIAL_SELL_PCT 0.70 on first sell, remaining on second
- [x] Config: `configs/analysts/vinod_spx.json`, `configs/analysts/vinod_other.json` (channel IDs filled in)
- [x] Parser tests: 27 tests, all passing (buy/sell regex, author filter, strategy filter)

### M1.3 — Master Analyst (basic) ✅
- [x] `master/master_analyst.py` — async signal queue consumer
- [x] Dedup: same analyst + same symbol + same expiry within 5 min → drop
- [x] Kill-switch check before every approval
- [x] LLM inference: Claude call with evidence → approve / reject with reason
- [x] All rejections logged (never silently dropped)
- [x] Approved signals forwarded to RH Gateway queue

### M1.4 — RH Gateway ✅
- [x] `gateway/rh_gateway.py` — paper mode, idempotent orders, position tracking
- [x] All prices stored as `price_per_share` AND `price_per_contract` — no ambiguity
- [x] `client_order_id` = SHA256(analyst_id + symbol + strike + expiry + direction + qty + date)
- [x] Redis idempotency cache (24h TTL, local dict fallback)
- [x] Paper mode: simulated fills, in-memory positions
- [x] Guards: min ask $0.10, max OTM% for 0DTE = 2%

### M1.5 — Monitor Agent (basic) ✅
- [x] `gateway/monitor_agent.py` — runs per open position every 30s
- [x] `FIRST_SELL_FROM_SOURCE` strategy: listen on source channel, close 100% on first sell
- [x] `PARTIAL_SELL_PCT` strategy: 70% on first sell, remainder on second
- [x] Hard stops (ALL positions, ALL strategies): -50% disaster backstop, +100% gift close
- [x] Market-close sweep: close all positions 5 min before 4:00 PM ET
- [x] Telegram alert on every fill, stop, error

### M1.6 — Integration test ✅
- [x] Fake Discord message → Vinod analyst parses → TradeSignal emitted
- [x] Master Analyst receives (LLM mocked) → approves → sends to RH Gateway
- [x] Paper order placed → OrderRecord returned
- [x] End-to-end test passing in tests/integration/test_full_pipeline.py

---

## Phase 2 — All Discord Analysts
**Goal:** All 6 Discord channels running in paper mode.
**Duration:** Week 5–6

### M2.1 — Albert Analyst ✅
- [x] `analysts/discord/albert.py`
- [x] Gate: only active during earnings periods (earnings calendar check)
- [x] Exit: MANUAL — no auto-close, dashboard button + Telegram command

### M2.2 — Zabes Analyst (Main + ZAPs) ✅
- [x] `analysts/discord/zabes.py`
- [x] Swing trade detection (multi-day holds)
- [x] Exit: `OWNER_FIRST_SELL` — close when Zabes/ZAPs owner posts first sell

### M2.3 — ADI Analyst (Premium Alerts) ✅
- [x] `analysts/discord/adi.py`
- [x] SPX trades only
- [x] Exit: `FIRST_SELL_FROM_SOURCE` — same logic as Vinod SPX

### M2.4 — Pilla Swings Analyst ✅
- [x] `analysts/discord/pilla_swings.py`
- [x] Exit: `OWNER_LAST_SELL` — close after owner's last sell (no new sell msg in 10 min)

### M2.5 — Everest Analyst ✅
- [x] `analysts/discord/everest.py`
- [x] Exit: MANUAL — user sells via dashboard / Telegram

### M2.6 — Dashboard (basic) ✅
- [x] FastAPI server: open positions, per-analyst P&L, recent signals, kill-switch toggle
- [x] Simple HTML/Tailwind frontend (no React yet)
- [x] Manual sell button per position (for Albert, Everest)

---

## Phase 3 — Unusual Whales Analysts
**Goal:** UW-driven analysts live in paper mode. Memory Journal writing.
**Duration:** Week 7–9

### M3.1 — UW Client ✅
- [x] `analysts/unusual_whales/uw_client.py`
- [x] Version-pinned endpoint constants + startup health-check
- [x] Token-bucket rate limiting (respect UW API limits)
- [x] File cache fallback: if endpoint 404 → serve cached response + alert operator

### M3.2 — Mag7 Analyst ✅
- [x] `analysts/unusual_whales/mag7.py`
- [x] Configurable watchlist via `configs/analysts/mag7_watchlist.json` (upload, not hardcoded)
- [x] Weekly call selection logic
- [x] Scoring: momentum + social spike + option volume vs 20-day avg + events + UW unusual bets + sector rotation
- [x] Evidence threshold: 3+ signals agreeing
- [x] Exit: PRICE_TARGET (1.05x) OR MANUAL (whichever first)

### M3.3 — SPY/SPX UW Analyst ✅
- [x] `analysts/unusual_whales/spy_spx.py`
- [x] Daily trades, wake every 5 min during RTH
- [x] Tracks: total call/put volume ratio, GEX, Trump tweet hook, unusual Mag7 volume, sector strength
- [x] Directional bias → SPY or SPX call or put selection

### M3.4 — Options Screener Analyst ✅
- [x] `analysts/unusual_whales/screener.py`
- [x] Unusual volume detection (>3× 20-day avg OI)
- [x] Move-capability check (market cap, float, beta)
- [x] Support/resistance + entry timing + expected exit date (earnings/catalyst)

### M3.5 — Memory Journal ✅
- [x] `master/memory_journal.py`
- [x] SQLite schema: signal_id, analyst_id, entry_price, exit_price, pnl, evidence_items, market_conditions, outcome
- [x] Write on every position close
- [x] Query: win rate per analyst, per pattern type

---

## Phase 4 — Social + Technical Analysts
**Goal:** Full 11-analyst suite active in paper mode.
**Duration:** Week 10–12

### M4.1 — Social Trends Analyst ✅
- [x] `analysts/social/social_trends.py`
- [x] Sources: Reddit (praw), StockTwits, Google Trends
- [x] 30-day rolling baseline per ticker (handles always-high names like TSLA)
- [x] Spike filter: >2σ above 30-day baseline required
- [x] Option volume minimum filter (below threshold → skip)
- [x] Headline news sentiment scoring
- [x] Exit: TA_RULES (Technical Analyst confirms exit)

### M4.2 — Technical Analyst ✅
- [x] `analysts/technical/technical_analyst.py`
- [x] SPY/SPX only
- [x] Indicators: FVG (Fair Value Gap), VWAP deviation, OBV trend, CVD, TICK Index, Put/Call ratio trend, VIX term structure
- [x] Evidence rule: ≥2 indicators agreeing + confirmation candle
- [x] Wake: every 5 min during RTH
- [x] Also used by Monitor Agent to cross-check open positions

### M4.3 — Master Analyst upgrades ✅
- [x] Memory Journal queries before approval: analyst win-rate lookup
- [x] Weight signals by analyst historical performance (RL gate auto-rejects < 40% win rate)
- [x] Conflict detection: two analysts with opposing directions on same ticker → flag

### M4.4 — TA Rules in Monitor Agent ✅
- [x] Every 5 min: cross-check all open positions against Technical Analyst output
- [x] If TA contradicts position direction AND position is profitable → flag for early exit review
- [x] Log all cross-checks for future RL training data

---

## Phase 5 — Live Trading + RL Loop
**Goal:** Paper → live, Master Analyst starts making rejection decisions, RL loop running.
**Duration:** Week 13–16

### M5.1 — Live mode
- [ ] `PAPER_TRADING_MODE=false` in `.env` → switches all gateway calls to real RH API
- [ ] Pre-live checklist: all hard guards tested, kill-switch tested, Telegram alerts working
- [ ] Start with 1 analyst only (Vinod SPX), expand weekly

### M5.2 — Master Analyst RL ✅
- [x] EOD evaluation: for each analyst, compute 7-day win rate by evidence pattern
- [x] If analyst win rate < 40% on pattern → reject similar signals automatically
- [x] Max 3 parameter changes per EOD eval, within hard limits
- [x] All auto-changes logged (human can revert via dashboard)

### M5.3 — Monitor Agent RL ✅
- [x] Track which exit rules performed best per analyst
- [x] Adjust stop-loss tightness based on analyst's historical volatility
- [x] Learned rules stored in `shared/monitor_rules.json`, applied next session

### M5.4 — Production deployment ✅
- [x] k3s cluster (or existing k8s from Legacy project)
- [x] Helm chart for all services
- [x] Doppler secrets (no `.env` in production)
- [x] ArgoCD GitOps (push to main → auto deploy)
- [x] Grafana dashboards: analyst P&L, signal flow rate, RH gateway latency, monitor actions

---

## Analyst Summary Table

| Analyst | Source | Wake Trigger | Symbols | Exit Strategy |
|---|---|---|---|---|
| Vinod SPX | Discord (main server) | Discord message | SPX only | First sell from Vinod |
| Vinod Other | Discord (main server) | Discord message | Everything else | 70% on first sell |
| Albert | Discord (main server) | Discord message | All (earnings only) | Manual |
| Zabes + ZAPs | Discord (main + Premium) | Discord message | Swings | Owner first sell |
| ADI | Discord (Premium Alerts) | Discord message | SPX | First sell from ADI |
| Pilla Swings | Pillow Swings server | Discord message | All | Owner last sell |
| Everest | Everest server | Discord message | All | Manual |
| Mag7 | Unusual Whales | 15 min schedule | Configurable watchlist | 1.05x target or Manual |
| SPY/SPX UW | Unusual Whales | 5 min schedule | SPY, SPX | TA Rules |
| Options Screener | Unusual Whales | 5 min schedule | Screener output | Catalyst/earnings date |
| Social Trends | Reddit/StockTwits/News | 10 min schedule | Social spike tickers | TA Rules |
| Technical | TA engine | 5 min schedule | SPY, SPX | TA-driven |

---

## Hard Rules (Never Negotiated)

These cannot be turned off, even by the kill-switch:

1. `PAPER_TRADING_MODE` must be explicitly set to `false` in `.env` to go live
2. Min option ask price: $0.10
3. Max OTM% for 0DTE options: 2%
4. Disaster backstop: close any position at -50% loss, regardless of exit strategy
5. Gift close: close any position at +100% gain
6. Market close sweep: close all positions 5 min before 4:00 PM ET
7. Kill-switch safe-fail: missing file = BLOCKED, malformed JSON = BLOCKED
8. `client_order_id` must be deterministic and Redis-cached (no duplicate orders)
9. All analyst rejections must be logged (no silent drops)
10. All prices stored as both `price_per_share` and `price_per_contract` in every record
