import httpx
from database import get_active_users
from pybit.unified_trading import HTTP


def place_order(api_key, api_secret, symbol, side, qty, tp=None, sl=None):
    try:
        session = HTTP(api_key=api_key, api_secret=api_secret)
        params = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty,
        }

        if tp:
            params["takeProfit"] = str(tp)
        if sl:
            params["stopLoss"] = str(sl)

        response = session.place_order(**params)
        return response
    except Exception as e:
        print(f"❌ Ошибка при открытии ордера: {e}")
        return None


def distribute_signal(signal: dict):
    """
    signal = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "qty": 0.01,
        "take_profit": 31500.0,
        "stop_loss": 29200.0
    }
    """
    users = get_active_users()
    if not users:
        print("⛔️ Нет активных пользователей для копирования.")
        return

    for user in users:
        print(f"📤 Копируем ордер для пользователя {user['user_id']}")

        response = place_order(
            api_key=user["api_key"],
            api_secret=user["api_secret"],
            symbol=signal["symbol"],
            side=signal["side"],
            qty=signal["qty"],
            tp=signal.get("take_profit"),
            sl=signal.get("stop_loss"),
        )

        if response and response.get("retCode") == 0:
            print(f"✅ Ордер успешно размещён для пользователя {user['user_id']}")
        else:
            print(f"⚠️ Не удалось разместить ордер для {user['user_id']}: {response}")
