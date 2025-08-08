from dotenv import load_dotenv
import os
load_dotenv()

from pybit.unified_trading import HTTP
from telegram import Bot
from pymongo import MongoClient
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import logging

# ⚠️ Лучше хранить в .env, но оставляю как в твоём примере
BOT_TOKEN = "8128401211:AAG0K7GG23Ia4afmChkaXCct2ULlbP1-8c4"
bot = Bot(token=BOT_TOKEN)

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
users_collection = client["signal_bot"]["users"]
history_collection = client["signal_bot"]["history"]

# ===================== i18n =====================
TEXTS = {
    "ru": {
        "opened_title": "📈 *На вашем аккаунте открыта сделка*",
        "closed_title": "🛑 *На вашем аккаунте закрыта сделка*",
        "pair": "🔹 Пара",
        "side": "🧭 Сторона",
        "entry": "🎯 Вход",
        "qty": "💼 Объём",
        "lev": "⚙️ Плечо",
        "time": "📅 Время",
        "buy": "Buy",
        "sell": "Sell",
    },
    "en": {
        "opened_title": "📈 *A trade has been opened on your account*",
        "closed_title": "🛑 *A trade has been closed on your account*",
        "pair": "🔹 Pair",
        "side": "🧭 Side",
        "entry": "🎯 Entry",
        "qty": "💼 Size",
        "lev": "⚙️ Leverage",
        "time": "📅 Time",
        "buy": "Buy",
        "sell": "Sell",
    },
}

def tr(lang: str, key: str) -> str:
    lang = "en" if lang == "en" else "ru"
    return TEXTS[lang][key]
# =================================================

def round_qty(qty, step):
    """Округление количества по шагу лота вниз."""
    return float(Decimal(qty).quantize(Decimal(step), rounding=ROUND_DOWN))


def _is_hedge_mode(positions_list):
    """
    Грубая, но рабочая проверка: если у позиций встречается positionIdx 1/2 — считаем Hedge Mode включён.
    """
    for p in positions_list or []:
        try:
            idx = int(p.get("positionIdx", 0))
            if idx in (1, 2):
                return True
        except Exception:
            pass
    return False


async def open_trade_for_all_clients(symbol, side, entry_price, leverage, tp=None, sl=None):
    logging.info("📤 Открытие сделок для всех пользователей...")

    for user in users_collection.find({
        "copy_enabled": True,
        "api_key": {"$exists": True, "$ne": None},
        "api_secret": {"$exists": True, "$ne": None}
    }):
        user_id = user["user_id"]
        chat_id = user.get("chat_id")
        fixed_usdt = float(user.get("fixed_usdt", 10))
        signals_left = int(user.get("signals_left", 0))
        lang = user.get("lang", "ru")  # i18n

        if signals_left <= 0:
            logging.info(f"[⛔ SKIP] user_id={user_id}, нет доступных сигналов.")
            users_collection.update_one({"user_id": user_id}, {"$set": {"copy_enabled": False}})
            continue

        try:
            session = HTTP(api_key=user["api_key"], api_secret=user["api_secret"], recv_window=10000)

            # 1) Информация по инструменту
            info = session.get_instruments_info(category="linear", symbol=symbol)
            info_list = (info or {}).get("result", {}).get("list", [])
            if not info_list:
                logging.warning(f"[⚠️ NO INSTRUMENT INFO] user_id={user_id}, symbol={symbol}")
                continue

            lot_info = info_list[0].get("lotSizeFilter", {})
            step = lot_info.get("qtyStep", "0.001")
            min_qty = float(lot_info.get("minOrderQty", step))

            # 2) Проверка текущих позиций и определение режима (hedge/one-way)
            pre_positions = session.get_positions(category="linear", symbol=symbol).get("result", {}).get("list", [])
            hedge_mode = _is_hedge_mode(pre_positions)

            # Защита от повторного открытия
            if hedge_mode:
                dup = next((p for p in pre_positions
                            if p.get("symbol") == symbol
                            and p.get("side") == side
                            and float(p.get("size", 0)) > 0), None)
                if dup:
                    logging.info(f"[⏭ SKIP DUP OPEN] user_id={user_id}, {symbol} уже открыт {side} (hedge)")
                    continue
            else:
                one = next((p for p in pre_positions
                            if p.get("symbol") == symbol
                            and float(p.get("size", 0)) > 0), None)
                if one and one.get("side") == side:
                    logging.info(f"[⏭ SKIP DUP OPEN] user_id={user_id}, {symbol} уже открыт {side} (one-way)")
                    continue

            # 3) Расчёт объёма
            raw_qty = (fixed_usdt * float(leverage)) / max(float(entry_price), 1e-9)
            qty = round_qty(raw_qty, step)
            if qty < min_qty:
                logging.warning(f"[⚠️ SKIP] user_id={user_id}, qty={qty} < min={min_qty} for {symbol}")
                continue

            # 4) Попытка выставить плечо (не критично)
            try:
                session.set_leverage(
                    category="linear",
                    symbol=symbol,
                    buyLeverage=leverage,
                    sellLeverage=leverage
                )
            except Exception as e:
                logging.warning(f"[⚠️ LEVERAGE FAIL] user_id={user_id}, {symbol}: {e}")

            # 5) Параметры ордера
            order_params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "order_type": "Market",
                "qty": str(qty),
                "time_in_force": "GoodTillCancel",
            }
            if hedge_mode:
                order_params["position_idx"] = 1 if side == "Buy" else 2

            if tp is not None:
                order_params["take_profit"] = round(float(tp), 4)
            if sl is not None:
                order_params["stop_loss"] = round(float(sl), 4)

            # 6) Размещаем ордер (c безопасным ретраем без position_idx при ошибке)
            try:
                session.place_order(**order_params)
            except Exception as e:
                msg = str(e)
                if "position idx not match position mode" in msg and "position_idx" in order_params:
                    # Повторить без position_idx (на случай неверной авто-детекции)
                    bad = order_params.pop("position_idx", None)
                    logging.warning(f"[↩️ RETRY] user_id={user_id}, удаляю position_idx={bad} и повторяю place_order")
                    session.place_order(**order_params)
                else:
                    raise

            # 7) Обновим баланс сигналов
            users_collection.update_one({"user_id": user_id}, {"$inc": {"signals_left": -1}})

            # 8) Читаем актуальные позиции после размещения ордера
            post_positions = session.get_positions(category="linear", symbol=symbol).get("result", {}).get("list", [])
            if hedge_mode:
                new_pos = next((p for p in post_positions
                                if p.get("symbol") == symbol
                                and p.get("side") == side
                                and float(p.get("size", 0)) > 0), None)
            else:
                new_pos = next((p for p in post_positions
                                if p.get("symbol") == symbol
                                and float(p.get("size", 0)) > 0), None)

            avg_price = float(new_pos.get("avgPrice", entry_price)) if new_pos else float(entry_price)

            # 9) Логируем ОТКРЫТИЕ в историю (важно: exit=0 и status='open')
            history_collection.insert_one({
                "user_id": user_id,
                "symbol": symbol,
                "side": side,
                "entry": avg_price,
                "size": qty,
                "tp": float(tp) if tp is not None else 0.0,
                "sl": float(sl) if sl is not None else 0.0,
                "exit": 0.0,
                "status": "open",
                "timestamp": datetime.utcnow()
            })

            # 10) Сообщаем только клиенту (i18n)
            if chat_id:
                side_txt = tr(lang, "buy") if side == "Buy" else tr(lang, "sell")
                msg = (
                    f"{tr(lang, 'opened_title')}\n"
                    f"{tr(lang, 'pair')}: {symbol}\n"
                    f"{tr(lang, 'side')}: {side_txt}\n"
                    f"{tr(lang, 'entry')}: {avg_price}\n"
                    f"{tr(lang, 'qty')}: {qty}\n"
                    f"{tr(lang, 'lev')}: {leverage}x"
                )
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

            logging.info(f"[✅ TRADE OPENED] user_id={user_id}, {symbol} {side} qty={qty}")

        except Exception as e:
            logging.error(f"[❌ ERROR] user_id={user_id}: {e}", exc_info=True)


async def close_trade_for_all_clients(symbol: str):
    logging.info("📤 Закрытие сделок...")

    for user in users_collection.find({
        "copy_enabled": True,
        "api_key": {"$exists": True, "$ne": None},
        "api_secret": {"$exists": True, "$ne": None}
    }):
        user_id = user["user_id"]
        chat_id = user.get("chat_id")
        lang = user.get("lang", "ru")  # i18n

        try:
            session = HTTP(api_key=user["api_key"], api_secret=user["api_secret"], recv_window=10000)

            positions = session.get_positions(category="linear", symbol=symbol).get("result", {}).get("list", [])
            # Любая активная позиция по этому символу
            position = next((p for p in positions if p.get("symbol") == symbol and float(p.get("size", 0)) > 0), None)
            if not position:
                continue

            side_to_close = "Sell" if position.get("side") == "Buy" else "Buy"
            qty = float(position.get("size"))
            position_idx = int(position.get("positionIdx", 0))

            close_order = {
                "category": "linear",
                "symbol": symbol,
                "side": side_to_close,
                "order_type": "Market",
                "qty": str(qty),
                "time_in_force": "GoodTillCancel",
                "reduce_only": True
            }
            if position_idx in (1, 2):
                close_order["position_idx"] = position_idx

            # Закрываем (с ретраем на случай несоответствия режима)
            try:
                session.place_order(**close_order)
            except Exception as e:
                msg = str(e)
                if "position idx not match position mode" in msg and "position_idx" in close_order:
                    bad = close_order.pop("position_idx", None)
                    logging.warning(f"[↩️ RETRY CLOSE] user_id={user_id}, удаляю position_idx={bad} и повторяю place_order")
                    session.place_order(**close_order)
                else:
                    raise

            # Сохраняем факт закрытия (status='close', реальные цены)
            entry_price = float(position.get("avgPrice", 0))
            # после закрытия лучше дёрнуть последнюю markPrice снова — но берём из позиции, которая была
            exit_price = float(position.get("markPrice", 0))

            history_collection.insert_one({
                "user_id": user_id,
                "symbol": symbol,
                "side": side_to_close,
                "entry": entry_price,
                "size": qty,
                "tp": 0.0,
                "sl": 0.0,
                "exit": exit_price,
                "status": "close",
                "timestamp": datetime.utcnow()
            })

            # Уведомляем клиента о закрытии (i18n)
            if chat_id:
                msg = (
                    f"{tr(lang, 'closed_title')}\n"
                    f"{tr(lang, 'pair')}: {symbol}\n"
                    f"{tr(lang, 'qty')}: {qty}\n"
                    f"{tr(lang, 'time')}: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

            logging.info(f"[🛑 CLOSED] user_id={user_id}, {symbol} qty={qty}")

        except Exception as e:
            logging.error(f"[❌ CLOSE ERROR] user_id={user_id}: {e}", exc_info=True)
