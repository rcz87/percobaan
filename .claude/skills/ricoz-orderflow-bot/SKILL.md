---
name: ricoz-orderflow-bot
description: >
  Skill for operating, developing, debugging, and deploying the RICOZ Order Flow Bot —
  a Python CEX auto-trading bot for Binance Futures using CoinGlass order flow signals
  (SpotCVD, FutCVD, Liquidation, OI, Taker Volume) via McPCG MCP server.
  Use this skill whenever working with the ricoz-bot Python codebase, CCXT execution engine,
  signal engine scoring, state manager, paper trading, Telegram bot commands,
  McPCG/CoinGlass data fetching, SQLite trade database, or any task related to
  the CEX order flow auto-trading infrastructure.
  Trigger on: "ricoz bot", "order flow bot", "ricoz order flow", "CEX bot",
  "binance bot", "signal engine", "SpotCVD gate", "FutCVD", "paper trading",
  "execution engine", "state manager", "McPCG fetcher", "signal score",
  "CCXT", "binance testnet", "order manager", "SL/TP", "cooldown",
  "drawdown guard", "kill switch", "daily PnL", "/status", "/stop", "/go",
  "close_all", "paper monitor", "signal loop", "entry decision",
  "coinglass_spot_cvd", "coinglass_futures_cvd", or any reference to
  CEX auto-trading with order flow signals on Binance Futures.
---

# RICOZ Order Flow Bot — Claude Code Skill

## Overview

RICOZ Order Flow Bot is a Python async auto-trading bot for **Binance Futures** that uses
**CoinGlass order flow data** (via McPCG MCP server) to generate entry signals, score them,
and execute trades with automatic SL/TP management.

**Core philosophy:** Order Flow > Indicators. SpotCVD is ground truth. SL is MANDATORY. SHORT = equal opportunity.

**Tech stack:** Python 3.11+ | CCXT 4.x | SQLite | python-telegram-bot 20.x | aiohttp | PM2

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   DATA LAYER                         │
│   CoinGlass (McPCG)       │   Binance (CCXT)         │
│   - SpotCVD    ← #1 VETO  │   - Price feed           │
│   - FutCVD     ← #2 VETO  │   - Order execution      │
│   - Liquidation            │   - Position tracking     │
│   - OI, Taker              │                           │
└──────────────┬──────────────────────────────────────┘
               ↓
┌─────────────────────────────────────────────────────┐
│              SIGNAL ENGINE (src/signal/)              │
│  1. SpotCVD gate    → sustained 3+ candles (VETO)    │
│  2. FutCVD align    → must match SpotCVD (VETO)      │
│  3. Liquidation     → confluence check               │
│  4. OI + Taker      → confirmation                   │
│  5. Score 0-100     → sizing: ≥90=full ≥80=75% ≥75=50% │
└──────────────┬──────────────────────────────────────┘
               ↓
┌─────────────────────────────────────────────────────┐
│              STATE MANAGER (src/state/)               │
│  - Open position guard    - Max positions (2)         │
│  - Cooldown (300s)        - Daily drawdown (3%)       │
│  - Kill switch (/stop)    - Fee-inclusive PnL          │
└──────────────┬──────────────────────────────────────┘
               ↓
┌─────────────────────────────────────────────────────┐
│            EXECUTION ENGINE (src/executor/)           │
│  CCXT → Binance Futures (testnet or live)             │
│  - Market order entry     - @retrier decorator        │
│  - SL/TP auto-set         - Precision enforcement     │
│  - Partial fill handler   - Emergency close           │
└──────────────┬──────────────────────────────────────┘
               ↓
┌─────────────────────────────────────────────────────┐
│             TELEGRAM LAYER (src/telegram/)            │
│  /status /pnl /stats /history /paper                  │
│  /stop /go /close_all /test_order                     │
└─────────────────────────────────────────────────────┘
```

## Project Structure

```
ricoz-bot/
├── src/
│   ├── config.py                 ← .env loader + validation + safety guards
│   ├── main.py                   ← Main loop: signal_loop + position_monitor + paper_monitor
│   ├── executor/
│   │   ├── binance_client.py     ← CCXT async wrapper + @retrier decorator
│   │   ├── order_manager.py      ← Full order lifecycle: entry → SL/TP → exit
│   │   ├── sl_tp.py              ← STOP_MARKET + TAKE_PROFIT_MARKET placement
│   │   └── partial_fill.py       ← Timeout + cancel sisa logic
│   ├── signal/
│   │   ├── fetcher.py            ← CoinGlass data via McPCG (JSON-RPC / SSE)
│   │   ├── engine.py             ← Scoring (0-100) + entry decision logic
│   │   ├── cvd.py                ← SpotCVD/FutCVD analyzer + liquidation/taker confluence
│   │   └── parser.py             ← Markdown table → structured data parser
│   ├── state/
│   │   ├── manager.py            ← Entry guard + PnL recording + kill switch + paper trading
│   │   └── db.py                 ← SQLite schema + CRUD + analytics queries
│   └── telegram/
│       ├── bot.py                ← Command handlers + @authorized_only decorator
│       └── alerts.py             ← Entry/exit/error/startup/shutdown notifications
├── scripts/
│   └── test_testnet.py           ← Phase 1 verification (10-step integration test)
├── tests/
│   ├── test_executor.py          ← SL/TP math + retry + PnL calculation tests
│   ├── test_signal.py            ← Parser + CVD analyzer + SignalEngine tests
│   ├── test_state.py             ← Database CRUD + StateManager guard tests
│   └── test_paper.py             ← Paper trading lifecycle + integration tests
├── data/                         ← SQLite DB (gitignored)
├── logs/                         ← Daily rotation logs (gitignored)
├── .env.example                  ← Template env vars
├── blueprint                     ← Full system blueprint doc
└── requirements.txt              ← Python dependencies
```

---

## BUILD PHASES

The project follows a strict bottom-up build order. **Never skip phases.**

| Phase | Module | Status Check |
|-------|--------|-------------|
| **Phase 1** | Execution Engine | `python scripts/test_testnet.py` |
| **Phase 2** | State Manager | `pytest tests/test_state.py -v` |
| **Phase 3** | Signal Engine | `pytest tests/test_signal.py -v` |
| **Phase 4** | Integration + Paper | `pytest tests/test_paper.py -v` + paper trading results |
| **Phase 5** | Live Trading | Real money — only after Phase 1-4 all green |

---

## SIGNAL LOGIC — Critical Rules

### Hard Vetoes (non-negotiable)

1. **SpotCVD Gate (Veto #1):** Must be sustained 3+ candles in same direction. Single flip = REJECT.
2. **FutCVD Alignment (Veto #2):** Must align with SpotCVD. Divergence = hedging = REJECT.
3. **Stale Signal:** Data older than 10 seconds = REJECT (do not execute).

### Scoring Breakdown (max 100)

| Signal | Max Points | Priority |
|--------|-----------|----------|
| SpotCVD (sustained + strength) | 30 | #1 — determines direction |
| FutCVD (alignment + strength) | 25 | #2 — must align |
| Liquidation (confluence) | 20 | #3 — confirmation |
| Open Interest (rising) | 15 | #4 — confirmation |
| Taker Volume (dominant) | 10 | #5 — confirmation |

### Entry Sizing

| Score | Decision | Size |
|-------|----------|------|
| ≥ 90 | ENTRY_FULL | 100% of AUTO_BUY_AMOUNT_USDT |
| ≥ 80 | ENTRY_75 | 75% |
| ≥ MIN_SCORE (75) | ENTRY_50 | 50% |
| < MIN_SCORE | REJECT | No entry |

### Direction Logic

- SpotCVD sustained **rising** → side = `buy` (long)
- SpotCVD sustained **falling** → side = `sell` (short)
- **SHORT = equal opportunity to LONG** — never skip shorts

---

## EXECUTION ENGINE — Key Patterns

### @retrier Decorator (Freqtrade pattern)
Located in `src/executor/binance_client.py`. Quadratic backoff for network errors:
```
Attempt 0: wait (4-0)²+1 = 17s
Attempt 1: wait (4-1)²+1 = 10s
Attempt 2: wait (4-2)²+1 = 5s
Attempt 3: wait (4-3)²+1 = 2s
```
- Retries: `NetworkError`, `DDoSProtection`
- Fatal (no retry): `InsufficientFunds`, `InvalidOrder`, `AuthenticationError`, `ExchangeError`

### Precision Enforcement
Always use `exchange.amount_to_precision()` and `exchange.price_to_precision()` before placing orders.

### SL/TP Pattern
- SL = `STOP_MARKET` with `reduceOnly: True`
- TP = `TAKE_PROFIT_MARKET` with `reduceOnly: True`
- Default: SL 1.5%, TP 3.0% (2:1 RR)
- **SL is MANDATORY** — code raises ValueError if SL_PCT ≤ 0

### Partial Fill Handler
Market orders on futures are usually instant. Edge case handling:
1. Quick check order status
2. If not filled → wait 2s → recheck
3. If partial → cancel remaining, return filled qty
4. If zero fill → cancel all, return 0

---

## STATE MANAGER — Guard Logic

### Entry Guards (checked in order)
1. **Kill switch:** `is_stopped` → block all
2. **Duplicate:** Open position in same symbol → block
3. **Max positions:** ≥ MAX_POSITIONS (default 2) → block
4. **Cooldown:** < 300s since last close on same symbol → block
5. **Daily drawdown:** ≥ 3% of INITIAL_CAPITAL → block all

### PnL Calculation (fee-inclusive, Freqtrade pattern)
```python
# Long:  (close - entry) * qty * (1 - 0.0004)
# Short: (entry - close) * qty * (1 - 0.0004)
# Fee rate: 0.04% taker (Binance)
```

### Paper Trading
- Generates `paper-{uuid}` order IDs
- Records in same DB with `is_paper=1`
- Paper position monitor checks live price against SL/TP every 10s
- Separate stats via `get_paper_stats()`, `get_paper_history()`

---

## McPCG DATA FETCHER

### How It Works
`src/signal/fetcher.py` calls McPCG via HTTP JSON-RPC (Streamable HTTP):
```python
POST https://mcp.guardiansofthetoken.org/mcp
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {"name": "coinglass_spot_cvd", "arguments": {...}},
  "id": 1
}
```

### Tools Used
| Tool | Signal | Args |
|------|--------|------|
| `coinglass_spot_cvd` | SpotCVD | symbol, interval, limit |
| `coinglass_futures_cvd` | FutCVD | symbol, interval, limit |
| `coinglass_liquidation_cat` | Liquidation | symbol, action="coin_history", interval, limit |
| `coinglass_open_interest_cat` | OI | symbol, action="aggregated_history", interval, limit |
| `coinglass_futures_taker_cat` | Taker | symbol, action="coin_taker", interval, limit |

### Response Parsing
McPCG returns markdown tables. Parser (`src/signal/parser.py`) handles:
- Number formats: `+502,362` / `-$447.5K` / `$4.72B`
- Table extraction: pipe-delimited markdown → list of dicts
- Summary extraction: direction, ratio, net change via regex

### Response Modes
- **JSON:** `result.content[].text` → parse JSON
- **SSE:** `data:` lines → extract JSON-RPC result

---

## TELEGRAM COMMANDS

| Command | Function | Source |
|---------|----------|--------|
| `/status` | Bot mode + balance + positions + today PnL + drawdown | bot.py |
| `/balance` | Account balance (free/used/total) | bot.py |
| `/positions` | Detailed open positions with live PnL | bot.py |
| `/pnl` | Daily + weekly PnL + per-symbol breakdown | bot.py |
| `/stats` | All-time: win rate, R:R ratio, expectancy, best/worst | bot.py |
| `/paper` | Paper trading stats + open paper positions | bot.py |
| `/history` | Last 10 closed trades | bot.py |
| `/stop` | Kill switch — block all auto-entries | bot.py |
| `/go` | Resume auto-entries | bot.py |
| `/close_all` | Emergency close ALL positions | bot.py |
| `/test_order [symbol] [side] [amount]` | Place test order (testnet only) | bot.py |
| `/help` | Show all commands | bot.py |

All commands require `@authorized_only` — only TELEGRAM_CHAT_ID can access.

---

## DIAGNOSE: Check System Health

### Step 1: Is the process running?
```bash
pm2 list
pm2 logs ricoz-bot --lines 200 --nostream
```

### Step 2: Error scan
```bash
pm2 logs ricoz-bot --lines 1000 --nostream 2>&1 | grep -iE "error|exception|traceback|FATAL" | tail -20
```

### Step 3: Signal activity
```bash
# Signal evaluations
pm2 logs ricoz-bot --lines 500 --nostream 2>&1 | grep -i "\[SIGNAL\]" | tail -20

# Paper entries
pm2 logs ricoz-bot --lines 500 --nostream 2>&1 | grep -i "\[PAPER\]" | tail -10

# Rejections
pm2 logs ricoz-bot --lines 500 --nostream 2>&1 | grep -i "REJECT\|BLOCKED" | tail -10
```

### Step 4: McPCG health
```bash
# McPCG fetch errors
pm2 logs ricoz-bot --lines 500 --nostream 2>&1 | grep -iE "McPCG|timeout|coinglass" | tail -10

# Test McPCG connectivity
curl -s -X POST https://mcp.guardiansofthetoken.org/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python3 -m json.tool | head -20
```

### Step 5: Database health
```bash
cd /path/to/ricoz-bot

# Open positions
sqlite3 data/ricoz_bot.db "SELECT symbol, side, entry_price, size_usdt, entry_signal_score, is_paper, opened_at FROM positions WHERE status='open' ORDER BY opened_at DESC;"

# Today's stats
sqlite3 data/ricoz_bot.db "SELECT * FROM daily_stats WHERE date = date('now');"

# Recent closed trades
sqlite3 data/ricoz_bot.db "SELECT symbol, side, entry_price, close_price, pnl_usdt, pnl_pct, close_reason, is_paper, closed_at FROM positions WHERE status='closed' ORDER BY closed_at DESC LIMIT 10;"

# Win rate summary
sqlite3 data/ricoz_bot.db "
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN pnl_usdt > 0 THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN pnl_usdt <= 0 THEN 1 ELSE 0 END) as losses,
  ROUND(SUM(pnl_usdt), 4) as total_pnl,
  ROUND(AVG(CASE WHEN pnl_usdt > 0 THEN pnl_usdt END), 4) as avg_win,
  ROUND(AVG(CASE WHEN pnl_usdt < 0 THEN ABS(pnl_usdt) END), 4) as avg_loss
FROM positions WHERE status='closed';
"

# Paper vs live breakdown
sqlite3 data/ricoz_bot.db "
SELECT
  CASE WHEN is_paper=1 THEN 'PAPER' ELSE 'LIVE' END as mode,
  COUNT(*) as trades,
  ROUND(SUM(pnl_usdt), 4) as pnl
FROM positions WHERE status='closed'
GROUP BY is_paper;
"
```

### Step 6: Config check (safe — no secrets)
```bash
grep -E "^(PAPER_MODE|BINANCE_TESTNET|AUTO_BUY|MAX_POSITIONS|MIN_SCORE|SL_PCT|TP_PCT|COOLDOWN|LEVERAGE|SYMBOLS|SIGNAL_INTERVAL|SIGNAL_LOOP)" .env
```

### Step 7: Run tests
```bash
cd /path/to/ricoz-bot
source venv/bin/activate

# All tests
python -m pytest tests/ -v

# Specific phase
python -m pytest tests/test_executor.py -v   # Phase 1
python -m pytest tests/test_state.py -v      # Phase 2
python -m pytest tests/test_signal.py -v     # Phase 3
python -m pytest tests/test_paper.py -v      # Phase 4

# Phase 1 integration test (requires testnet .env)
python scripts/test_testnet.py
```

### Quick Diagnostic One-Liner
```bash
echo "=== PM2 ===" && pm2 list && echo "=== ERRORS ===" && pm2 logs ricoz-bot --lines 500 --nostream 2>&1 | grep -iE "error|exception" | tail -5 && echo "=== CONFIG ===" && grep -E "^(PAPER_MODE|BINANCE_TESTNET|AUTO_BUY|MAX_POSITIONS|SYMBOLS)" .env && echo "=== OPEN POSITIONS ===" && sqlite3 data/ricoz_bot.db "SELECT symbol, side, entry_price, is_paper FROM positions WHERE status='open';" && echo "=== TODAY ===" && sqlite3 data/ricoz_bot.db "SELECT * FROM daily_stats WHERE date=date('now');"
```

---

## COMMON ISSUES & FIXES

### Issue: McPCG fetch returning empty/error data
**Symptoms:** All signals show REJECT with "Insufficient CVD history"
**Check:**
```bash
pm2 logs ricoz-bot --lines 200 --nostream 2>&1 | grep -i "McPCG"
```
**Likely causes:**
1. McPCG server down → check `curl https://mcp.guardiansofthetoken.org/mcp`
2. SSE response not parsed correctly → check `fetcher.py:_parse_sse()`
3. Tool arguments wrong → verify symbol format (use "SOL" not "SOL/USDT:USDT")

### Issue: Paper positions never close (SL/TP never hit)
**Symptoms:** Paper positions stay open indefinitely
**Check:**
```bash
sqlite3 data/ricoz_bot.db "SELECT symbol, side, entry_price, sl_price, tp_price FROM positions WHERE status='open' AND is_paper=1;"
```
**Likely causes:**
1. Paper monitor not running → check `paper_position_monitor` task in main.py
2. Price fetch failing for symbol → check logs for price errors
3. SL/TP prices miscalculated → verify SL_PCT/TP_PCT in .env

### Issue: Binance testnet connection fails
**Check:**
```bash
python -c "
import ccxt.async_support as ccxt, asyncio
async def test():
    ex = ccxt.binanceusdm({'apiKey':'test','secret':'test'})
    ex.set_sandbox_mode(True)
    print(await ex.fetch_status())
    await ex.close()
asyncio.run(test())
"
```
**Fixes:**
1. Regenerate testnet API keys at https://testnet.binancefuture.com
2. Check if BINANCE_TESTNET=true in .env
3. CCXT version ≥ 4.0 required

### Issue: Signal stale rejections
**Symptoms:** `"Signal stale (Xs > 10s)"` in every cycle
**Cause:** McPCG response time exceeds 10s threshold
**Fix:** Either increase `SIGNAL_STALE_SECS` in engine.py or optimize parallel fetching

### Issue: Daily drawdown triggered too early
**Check:**
```bash
sqlite3 data/ricoz_bot.db "SELECT date, total_pnl_usdt FROM daily_stats ORDER BY date DESC LIMIT 7;"
```
**Fix:** Verify INITIAL_CAPITAL in .env matches actual capital. Drawdown = abs(loss) / INITIAL_CAPITAL × 100

### Issue: Telegram bot not responding
**Check:**
1. TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID set in .env
2. Bot token valid: `curl https://api.telegram.org/bot<TOKEN>/getMe`
3. Chat ID correct: send message to bot, check `getUpdates`

---

## DEVELOP: Key Patterns

### Adding a new signal source
1. Add fetch method in `src/signal/fetcher.py`:
   ```python
   async def _fetch_new_signal(self, base: str) -> dict:
       raw = await self._call_mcp_tool("coinglass_new_tool", {...})
       return parse_new_response(raw.get("data", ""))
   ```
2. Add parser in `src/signal/parser.py`
3. Add to parallel fetch in `fetch_signal_data()`
4. Add scoring in `src/signal/engine.py:_calculate_score()`
5. Add confluence check in `src/signal/cvd.py` if needed
6. Add tests in `tests/test_signal.py`

### Adding a new Telegram command
1. Add handler method in `src/telegram/bot.py`:
   ```python
   @authorized_only
   async def _cmd_new(self, update, context):
       ...
   ```
2. Register in `_register_handlers()`
3. Add to `/help` text

### Modifying SL/TP defaults
- Config: `SL_PCT` and `TP_PCT` in .env (0.015 = 1.5%, 0.030 = 3.0%)
- Code: `src/executor/sl_tp.py` for placement logic
- Validation: `src/config.py` enforces SL_PCT > 0 in live mode

### Adding a new state guard
Add check in `src/state/manager.py:can_enter()`:
```python
# N. Your new guard
if self.your_condition():
    return False, "Your reason"
```

### Modifying scoring weights
Edit `src/signal/engine.py:_calculate_score()`:
- SpotCVD: max 30 pts (base 10 for passing gate)
- FutCVD: max 25 pts (base 8 for passing alignment)
- Liquidation: max 20 pts
- OI: max 15 pts (base 5 for rising)
- Taker: max 10 pts

### Adding a new trading pair
Update `SYMBOLS` in .env:
```
SYMBOLS=SOL/USDT:USDT,AVAX/USDT:USDT,SUI/USDT:USDT,BNB/USDT:USDT
```
Format: `{BASE}/USDT:USDT` (CCXT unified symbol for USDM futures)

---

## ENV VARS Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `BINANCE_API_KEY` | — | Binance API key (testnet or live) |
| `BINANCE_SECRET` | — | Binance API secret |
| `BINANCE_TESTNET` | `true` | Use testnet endpoint |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Authorized chat ID |
| `PAPER_MODE` | `true` | Simulate trades, no real orders |
| `AUTO_BUY_AMOUNT_USDT` | `5` | Base trade size |
| `MAX_POSITIONS` | `2` | Max concurrent positions |
| `MIN_SCORE` | `75` | Minimum signal score for entry |
| `SL_PCT` | `0.015` | Stop loss % (1.5%) |
| `TP_PCT` | `0.030` | Take profit % (3.0%) |
| `COOLDOWN_SECS` | `300` | Cooldown after close (5 min) |
| `LEVERAGE` | `1` | Futures leverage |
| `INITIAL_CAPITAL` | `500` | Capital base for drawdown calc |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Max daily drawdown % |
| `MAX_DAILY_LOSS_USDT` | `15` | Max daily loss absolute |
| `MAX_SINGLE_TRADE_USDT` | `50` | Cap per trade |
| `DB_PATH` | `./data/ricoz_bot.db` | SQLite database path |
| `MCPCG_URL` | `https://mcp.guardiansofthetoken.org/mcp` | McPCG endpoint |
| `SIGNAL_INTERVAL` | `5m` | CoinGlass candle interval |
| `SIGNAL_LOOKBACK` | `10` | Number of candles to fetch |
| `SIGNAL_LOOP_SECS` | `30` | Signal check interval |
| `SYMBOLS` | `SOL/USDT:USDT,...` | Comma-separated trading pairs |

---

## Database Schema

### positions
```sql
id TEXT PRIMARY KEY,
symbol TEXT, side TEXT, entry_price REAL, size_usdt REAL, qty REAL,
sl_price REAL, tp_price REAL, entry_signal_score INTEGER,
opened_at TIMESTAMP, closed_at TIMESTAMP, close_price REAL,
pnl_usdt REAL, pnl_pct REAL, close_reason TEXT,
status TEXT DEFAULT 'open',  -- 'open' | 'closed'
is_paper INTEGER DEFAULT 0,
signal_breakdown TEXT        -- JSON of scoring breakdown
```

### daily_stats
```sql
date TEXT PRIMARY KEY,
total_pnl_usdt REAL DEFAULT 0,
trades_count INTEGER DEFAULT 0,
wins INTEGER DEFAULT 0,
losses INTEGER DEFAULT 0
```

---

## OPERATE: Common Operations

### Setup from scratch
```bash
git clone <repo> ricoz-bot && cd ricoz-bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with API keys
mkdir -p data logs
```

### Run locally
```bash
source venv/bin/activate
python -m src.main
```

### Deploy with PM2
```bash
pm2 start "python -m src.main" --name ricoz-bot --cwd /path/to/ricoz-bot
pm2 save
pm2 logs ricoz-bot -f
```

### Switch paper ↔ live
```bash
# Enable live (DANGER)
sed -i 's/PAPER_MODE=true/PAPER_MODE=false/' .env
pm2 restart ricoz-bot

# Back to paper
sed -i 's/PAPER_MODE=false/PAPER_MODE=true/' .env
pm2 restart ricoz-bot
```

### Database backup
```bash
sqlite3 data/ricoz_bot.db ".backup 'data/ricoz_bot_backup_$(date +%Y%m%d_%H%M%S).db'"
```

### Run Phase 1 testnet verification
```bash
python scripts/test_testnet.py
# Tests: connect, balance, market order, SL/TP, partial fill, Telegram alerts, emergency close
```

---

## RISK RULES — Non-Negotiable

1. **SL WAJIB ada** — Position tanpa SL = emergency close. Code enforces `SL_PCT > 0`.
2. **Max daily loss 3%** — Bot auto-STOP. Reset next day.
3. **Max 2 positions** — 3rd entry blocked by state manager.
4. **Kill switch** — `/stop` blocks all entries instantly. `/go` to resume.
5. **Trade size cap** — `MAX_SINGLE_TRADE_USDT` enforced in order_manager.
6. **Stale signal rejection** — Signal > 10 seconds old = no execution.
7. **Log EVERYTHING** — Daily rotation, 30-day retention via loguru.

---

## Main Loop Flow (src/main.py)

Three concurrent async tasks run via `asyncio.gather`:

1. **`signal_loop`** (every 30s per symbol):
   Fetch → Evaluate → State check → Size → Paper/Live execute → Record → Notify

2. **`position_monitor`** (every 10s):
   Check exchange positions vs DB → detect SL/TP fills → record exit → notify

3. **`paper_position_monitor`** (every 10s):
   Check live price vs paper SL/TP → simulate exit → record → notify
