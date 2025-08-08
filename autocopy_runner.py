import time
import asyncio
from pybit.unified_trading import HTTP
from telegram import Bot
from database import users, log_trade, log_close_trade

# Telegram
TELEGRAM_TOKEN = "ВАШ_ТОКЕН_ТУТ"
bot = Bot(token=TELEGRAM_TOKEN)

# Мастер-ключи
MASTER_API_KEY = "TmjjxlaUBYl25XFy0A"
MASTER_API_SECRET = "GFZc9MtTs72Plvi1VurxmqiSMv4nL6DV2Axm"

# Хранит последнюю информацию по позициям
last_master = {}

def fetch_master_positions():
    session = HTTP(api_key=MASTER_API_KEY, api_secret=MASTER_API_SECRET)
    data = session.get_positions(category="linear")["result"]["list"]
    active = {}

    for p in data:
        size = float(p["size"])
        symbol = p["symbol"]
        if size > 0:
            active[symbol] = {
                "symbol": symbol,
                "side": p["side"],
                "entry": float(p["entryPrice"]),
                "size": size,
                "tp": p.get("takeProfit"),
                "sl": p.get("stopLoss")
            }
    return active

def calc_qty_by_percent(session, symbol, entry_price, pct):
    bal = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"]
    usdt = next((float(x["availableToTrade"]) for x in bal if x["coin"] == "USDT"), 0)
    usd_amount = usdt * pct / 100
    return round(usd_amount / entry_price, 3)

def open_trade(user, signal):
    sid = user["user_id"]
    session = HTTP(api_key=user["api_key"], api_secret=user["api_secret"])
    qty = calc_qty_by_percent(session, signal["symbol"], signal["entry"], user.get("percent", 2))
    if qty <= 0:
        bot.send_message(sid, f"⚠️ Недостаточно средств: {signal['symbol']}")
        return

    try:
        session.place_order(
            category="linear",
            symbol=signal["symbol"],
            side=signal["side"].capitalize(),
            order_type="Market",
            qty=qty,
            time_in_force="GoodTillCancel"
        )

        # SL / TP
        if signal["sl"] or signal["tp"]:
            session.set_trading_stop(
                category="linear",
                symbol=signal["symbol"],
                stop_loss=str(signal["sl"]) if signal["sl"] else None,
                take_profit=str(signal["tp"]) if signal["tp"] else None
            )

        # Логируем сделку
        log_trade(sid, signal["symbol"], signal["side"], signal["entry"], qty, signal["tp"], signal["sl"])
        bot.send_message(sid,
            f"✅ Открыта копия: {signal['symbol']} {signal['side']}\n"
            f"💰 Объём: {qty} (~{round(qty * signal['entry'], 2)} USDT)\n"
            f"🎯 TP: {signal['tp']} 🛡 SL: {signal['sl']}"
        )
    except Exception as e:
        bot.send_message(sid, f"❌ Ошибка открытия: {e}")

def close_trade(user, symbol):
    sid = user["user_id"]
    session = HTTP(api_key=user["api_key"], api_secret=user["api_secret"])
    try:
        positions = session.get_positions(category="linear")["result"]["list"]
        for p in positions:
            if p["symbol"] == symbol and float(p["size"]) > 0:
                close_side = "Sell" if p["side"] == "Buy" else "Buy"
                qty = float(p["size"])

                session.place_order(
                    category="linear",
                    symbol=symbol,
                    side=close_side,
                    order_type="Market",
                    qty=qty,
                    time_in_force="GoodTillCancel",
                    reduce_only=True
                )

                log_close_trade(sid, symbol, close_side, float(p["entryPrice"]), qty)
                bot.send_message(sid, f"🚪 Сделка закрыта: {symbol} ({close_side} {qty})")
    except Exception as e:
        bot.send_message(sid, f"❌ Ошибка закрытия {symbol}: {e}")

async def run_loop():
    global last_master
    while True:
        try:
            current = fetch_master_positions()

            # Проверка новых входов
            for symbol, signal in current.items():
                if symbol not in last_master:
                    for user in users.find({"copy_enabled": True}):
                        open_trade(user, signal)

            # Проверка на выход (закрытие позиции)
            closed_symbols = [s for s in last_master if s not in current]
            if closed_symbols:
                for user in users.find({"copy_enabled": True}):
                    for sym in closed_symbols:
                        close_trade(user, sym)

            last_master = current
        except Exception as e:
            print(f"[ERROR in loop] {e}")
        await asyncio.sleep(10)

if __name__ == "__main__":
    print("🚀 Запуск autocopy_runner.py")
    asyncio.run(run_loop())
