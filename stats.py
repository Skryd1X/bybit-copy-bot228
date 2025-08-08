from collections import defaultdict
from datetime import datetime
from pathlib import Path
import math

from database import history
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

# ─────────────────────────────────────────────────────────────────────────────
# Вспомогалки
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

def _is_closed_trade(doc: dict) -> bool:
    """
    Условие 'закрытой' сделки.
    1) Нормально: status == "close"
    2) Легаси: entry>0 и exit>0, но исключаем exit==1 (старый костыль логгера закрытия)
    """
    if doc.get("status") == "close":
        return True
    entry = _safe_float(doc.get("entry"))
    exit_ = _safe_float(doc.get("exit"))
    if entry > 0 and exit_ > 0 and exit_ != 1:
        return True
    return False

def _trade_pnl_usdt(entry: float, exit_: float, size: float, side: str) -> float:
    if entry <= 0 or exit_ <= 0 or size <= 0:
        return 0.0
    return (exit_ - entry) * size if side == "Buy" else (entry - exit_) * size

# ─────────────────────────────────────────────────────────────────────────────
# Текстовая статистика (компактная)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_full_stats(user_id: int) -> str:
    all_docs = list(history.find({"user_id": user_id}).sort("timestamp", 1))
    trades = [d for d in all_docs if _is_closed_trade(d)]

    if not trades:
        return "📊 У вас ещё не было завершённых сделок."

    total_trades = profitable = losing = breakeven = 0
    total_profit_pct = 0.0
    max_profit = -math.inf
    max_loss = math.inf

    per_symbol = defaultdict(lambda: {
        "count": 0,
        "profitable": 0,
        "losing": 0,
        "breakeven": 0,
        "total_pct": 0.0
    })

    for t in trades:
        entry = _safe_float(t.get("entry"))
        exit_  = _safe_float(t.get("exit"))
        side   = t.get("side")
        symbol = t.get("symbol", "UNKNOWN")

        if entry <= 0 or exit_ <= 0 or side not in ("Buy", "Sell"):
            continue

        profit_pct = ((exit_ - entry) / entry * 100.0) if side == "Buy" else ((entry - exit_) / entry * 100.0)

        total_trades += 1
        total_profit_pct += profit_pct
        max_profit = max(max_profit, profit_pct)
        max_loss = min(max_loss, profit_pct)

        if profit_pct > 0:
            profitable += 1
            per_symbol[symbol]["profitable"] += 1
        elif profit_pct < 0:
            losing += 1
            per_symbol[symbol]["losing"] += 1
        else:
            breakeven += 1
            per_symbol[symbol]["breakeven"] += 1

        per_symbol[symbol]["count"] += 1
        per_symbol[symbol]["total_pct"] += profit_pct

    if total_trades == 0:
        return "📊 Ваша история без завершённых сделок."

    avg_profit_pct = total_profit_pct / total_trades
    winrate = (profitable / total_trades) * 100.0

    summary = (
        f"📊 *Статистика торговли*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💼 Сделок: {total_trades}\n"
        f"🎯 Winrate: {winrate:.1f}%\n"
        f"📈 Средний результат: {avg_profit_pct:.2f}%\n"
        f"💰 Макс. прибыль: {max_profit:.2f}%\n"
        f"⚠️ Макс. убыток: {max_loss:.2f}%\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 *По инструментам:*\n"
    )

    # показываем не более 6 строк по инструментам
    lines = []
    for sym, s in per_symbol.items():
        if s["count"] == 0:
            continue
        avg_sym = s["total_pct"] / s["count"]
        win_sym = (s["profitable"] / s["count"]) * 100.0
        lines.append((s["count"], f"• {sym}: {s['count']} сделок | Winrate {win_sym:.1f}% | Ср. {avg_sym:.2f}%"))

    lines.sort(key=lambda x: -x[0])
    summary += "\n".join(line for _, line in lines[:6])
    if len(lines) > 6:
        summary += f"\n…и ещё {len(lines) - 6}"

    return summary

# ─────────────────────────────────────────────────────────────────────────────
# График equity-curve (накопленный PnL)
# ─────────────────────────────────────────────────────────────────────────────

def build_equity_curve_image(user_id: int):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    docs = list(history.find({"user_id": user_id}).sort("timestamp", 1))
    trades = [d for d in docs if _is_closed_trade(d)]

    points = []
    cum = 0.0
    for t in trades:
        entry = _safe_float(t.get("entry"))
        exit_  = _safe_float(t.get("exit"))
        size   = _safe_float(t.get("size"))
        side   = t.get("side")
        ts     = t.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        pnl = _trade_pnl_usdt(entry, exit_, size, side)
        cum += pnl
        points.append((ts, cum))

    if len(points) < 2:
        return None

    x = [p[0] for p in points]
    y = [p[1] for p in points]

    fig = plt.figure(figsize=(7, 3.6), dpi=150)
    ax = fig.add_subplot(111)
    ax.plot(x, y, linewidth=1.8)
    ax.set_title("Накопленный PnL (USDT)")
    ax.set_xlabel("Время")
    ax.set_ylabel("USDT")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    out_dir = Path("stats_media")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"equity_{user_id}.png"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path

# ─────────────────────────────────────────────────────────────────────────────
# Отправка в TG
# ─────────────────────────────────────────────────────────────────────────────

async def send_user_statistics(update, context: ContextTypes.DEFAULT_TYPE):
    """
    Работает и из callback-кнопки, и из нижнего текстового меню.
    """
    # Может прийти как callback_query, так и обычное текстовое сообщение
    query = getattr(update, "callback_query", None)

    # Универсально получаем user_id и chat_id
    user = update.effective_user
    chat = update.effective_chat

    user_id = query.from_user.id if query else (user.id if user else None)
    chat_id = (query.message.chat.id if (query and query.message) 
               else (chat.id if chat else user_id))

    if not user_id or not chat_id:
        return  # на всякий случай

    # Формируем текст и, если получится, картинку с equity
    text = calculate_full_stats(user_id)
    img_path = build_equity_curve_image(user_id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ])

    # Если это callback — отвечаем, чтобы убрать "часики"
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    # Отправляем в чат (для callback тоже отправляем новое сообщение — не редактируем старое)
    if img_path:
        with open(img_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )