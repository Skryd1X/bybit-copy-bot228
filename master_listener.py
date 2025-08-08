from pybit.unified_trading import HTTP
import logging

# 🔐 Данные мастера (лучше хранить в .env)
MASTER_API_KEY = "TmjjxlaUBYl25XFy0A"
MASTER_API_SECRET = "GFZc9MtTs72Plvi1VurxmqiSMv4nL6DV2Axm"

# 🟢 Получение сигналов с мастер-аккаунта
def get_signals():
    try:
        session = HTTP(api_key=MASTER_API_KEY, api_secret=MASTER_API_SECRET)
        response = session.get_positions(category="linear", settleCoin="USDT")

        positions = response.get("result", {}).get("list", [])
        signals = []

        for pos in positions:
            try:
                size = float(pos.get("size", 0))
                if size == 0:
                    continue  # Пропускаем закрытые позиции

                symbol = pos.get("symbol")
                side = pos.get("side")  # Buy / Sell
                entry = float(pos.get("entryPrice") or pos.get("avgPrice") or 0)
                leverage = float(pos.get("leverage", 1))
                tp = float(pos.get("takeProfit")) if pos.get("takeProfit") else None
                sl = float(pos.get("stopLoss")) if pos.get("stopLoss") else None

                signal = {
                    "symbol": symbol,
                    "side": side,
                    "entry": entry,
                    "leverage": leverage,
                    "tp": tp,
                    "sl": sl
                }

                signals.append(signal)

            except Exception as inner_error:
                logging.warning(f"⚠️ Ошибка при обработке позиции: {inner_error} — {pos}")
                continue

        return signals

    except Exception as e:
        logging.error(f"❌ Ошибка при получении сигналов от мастера: {e}")
        return []
