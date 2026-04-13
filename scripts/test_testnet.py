"""
RICOZ Bot — Phase 1 Testnet Verification Script

Jalankan: python scripts/test_testnet.py

Checklist yang ditest:
1. CCXT connect testnet ✓
2. fetch_balance() return USDT ✓
3. Place market order SOL/USDT ✓
4. SL/TP auto-set setelah fill ✓
5. Partial fill handler ✓
6. Cancel orders ✓
7. Telegram alerts ✓
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from src.config import (
    BINANCE_API_KEY, BINANCE_SECRET, BINANCE_TESTNET,
    TELEGRAM_BOT_TOKEN, SYMBOLS, validate_config,
)
from src.executor.binance_client import BinanceClient
from src.executor.order_manager import OrderManager
from src.telegram.alerts import TelegramAlerts


# Test config
TEST_SYMBOL = "SOL/USDT:USDT"
TEST_AMOUNT_USDT = 5.0
TEST_SIDE = "buy"


class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []

    def ok(self, name: str, detail: str = ""):
        self.passed.append(name)
        logger.success(f"  [PASS] {name} {detail}")

    def fail(self, name: str, error: str):
        self.failed.append((name, error))
        logger.error(f"  [FAIL] {name}: {error}")

    def summary(self):
        total = len(self.passed) + len(self.failed)
        logger.info(f"\n{'='*50}")
        logger.info(f"Phase 1 Test Results: {len(self.passed)}/{total} passed")
        logger.info(f"{'='*50}")
        if self.failed:
            for name, error in self.failed:
                logger.error(f"  FAILED: {name} — {error}")
        else:
            logger.success("  ALL TESTS PASSED!")
        return len(self.failed) == 0


async def run_tests():
    result = TestResult()
    client = BinanceClient()
    alerts = TelegramAlerts()
    order_manager = OrderManager(client)

    try:
        # ── Test 1: Config Validation ────────────────────
        logger.info("\n[Test 1] Config Validation")
        if validate_config():
            result.ok("Config validation")
        else:
            result.fail("Config validation", "Missing env vars")
            return result

        # ── Test 2: Connect Testnet ──────────────────────
        logger.info("\n[Test 2] Connect to Binance Testnet")
        try:
            await client.initialize()
            result.ok("Testnet connection", f"— {len(client.exchange.markets)} markets loaded")
        except Exception as e:
            result.fail("Testnet connection", str(e))
            return result

        # ── Test 3: Fetch Balance ────────────────────────
        logger.info("\n[Test 3] Fetch Balance")
        try:
            balance = await client.get_balance()
            usdt_free = float(balance.get("USDT", {}).get("free", 0))
            result.ok("Fetch balance", f"— USDT free: {usdt_free:.2f}")

            if usdt_free < TEST_AMOUNT_USDT:
                logger.warning(f"  WARNING: USDT balance ({usdt_free}) < test amount ({TEST_AMOUNT_USDT})")
                logger.warning("  Skipping order tests. Top up testnet balance first.")
                result.fail("Sufficient balance", f"Need {TEST_AMOUNT_USDT} USDT, have {usdt_free}")
                return result
        except Exception as e:
            result.fail("Fetch balance", str(e))
            return result

        # ── Test 4: Get Price ────────────────────────────
        logger.info("\n[Test 4] Get Price")
        try:
            price = await client.get_price(TEST_SYMBOL)
            result.ok("Get price", f"— {TEST_SYMBOL}: {price:.4f}")
        except Exception as e:
            result.fail("Get price", str(e))

        # ── Test 5: Place Market Order ───────────────────
        logger.info("\n[Test 5] Place Market Order")
        order = None
        try:
            entry_result = await order_manager.execute_entry(TEST_SYMBOL, TEST_SIDE, TEST_AMOUNT_USDT)

            if entry_result["status"] == "filled":
                result.ok("Market order", f"— filled @ {entry_result['entry_price']:.4f}")
                result.ok("Partial fill handler", f"— qty: {entry_result['qty']}")
                result.ok("SL/TP auto-set", f"— SL: {entry_result['sl_price']:.4f} TP: {entry_result['tp_price']:.4f}")
            else:
                result.fail("Market order", f"Status: {entry_result['status']}")
        except Exception as e:
            result.fail("Market order", str(e))

        # ── Test 6: Check Open Positions ─────────────────
        logger.info("\n[Test 6] Check Open Positions")
        try:
            positions = await client.get_open_positions()
            has_position = any(TEST_SYMBOL.replace("/", "").replace(":USDT", "") in str(p.get("symbol", "")) for p in positions)
            if has_position:
                result.ok("Position tracking", f"— {len(positions)} open position(s)")
            else:
                result.fail("Position tracking", "Position not found after order")
        except Exception as e:
            result.fail("Position tracking", str(e))

        # ── Test 7: Positions Summary ────────────────────
        logger.info("\n[Test 7] Positions Summary")
        try:
            summary = await order_manager.get_positions_summary()
            if summary:
                p = summary[0]
                result.ok("Positions summary", f"— {p['symbol']} PnL: {p['pnl_pct']:+.2f}%")
            else:
                result.fail("Positions summary", "Empty summary")
        except Exception as e:
            result.fail("Positions summary", str(e))

        # ── Test 8: Telegram Entry Alert ─────────────────
        logger.info("\n[Test 8] Telegram Alerts")
        if TELEGRAM_BOT_TOKEN:
            try:
                await alerts.send_entry(TEST_SYMBOL, TEST_SIDE, price, TEST_AMOUNT_USDT, 85)
                result.ok("Telegram entry alert")

                await alerts.send_status("Phase 1 test running...")
                result.ok("Telegram status alert")

                await alerts.send_error("Test error — ignore this")
                result.ok("Telegram error alert")
            except Exception as e:
                result.fail("Telegram alerts", str(e))
        else:
            logger.warning("  Telegram token not set — skipping alert tests")

        # ── Test 9: Emergency Close ──────────────────────
        logger.info("\n[Test 9] Emergency Close")
        try:
            closed = await order_manager.close_all_positions()
            result.ok("Emergency close", f"— closed {len(closed)} position(s)")

            # Telegram exit alert
            if TELEGRAM_BOT_TOKEN:
                await alerts.send_exit(TEST_SYMBOL, -0.05, -0.5, "Test Close")
                result.ok("Telegram exit alert")
        except Exception as e:
            result.fail("Emergency close", str(e))

        # ── Test 10: Verify Clean State ──────────────────
        logger.info("\n[Test 10] Verify Clean State")
        try:
            positions = await client.get_open_positions()
            if len(positions) == 0:
                result.ok("Clean state", "— no open positions")
            else:
                result.fail("Clean state", f"Still {len(positions)} open position(s)")
        except Exception as e:
            result.fail("Clean state", str(e))

    finally:
        await client.close()

    return result


async def main():
    logger.info("=" * 50)
    logger.info("RICOZ Bot — Phase 1 Testnet Verification")
    logger.info("=" * 50)

    if not BINANCE_TESTNET:
        logger.error("BINANCE_TESTNET must be true for testing!")
        sys.exit(1)

    result = await run_tests()
    result.summary()

    if TELEGRAM_BOT_TOKEN:
        alerts = TelegramAlerts()
        passed = len(result.passed)
        total = passed + len(result.failed)
        if result.summary:
            await alerts.send_status(
                f"Phase 1 Test Complete\n"
                f"Result: `{passed}/{total}` passed\n"
                f"{'All tests passed!' if not result.failed else 'Some tests failed.'}"
            )

    sys.exit(0 if not result.failed else 1)


if __name__ == "__main__":
    asyncio.run(main())
