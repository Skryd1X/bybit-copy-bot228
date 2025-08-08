from dotenv import load_dotenv
import os
load_dotenv()
from telegram import (
    Update,
    LabeledPrice
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters
)
from pymongo import MongoClient
import logging

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CRYPTOBOT_PROVIDER_TOKEN = os.getenv("CRYPTOBOT_PROVIDER_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
users_collection = client["signal_bot"]["users"]

# === Логирование ===
logging.basicConfig(level=logging.INFO)

# === Пакеты сигналов ===
SIGNAL_PACKAGES = {
    "15": 15,
    "35": 30,
    "60": 50
}

# === Команда /buy ===
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # ❗ По умолчанию пакет 15 (можно кастомизировать)
    amount = "15"
    signals = SIGNAL_PACKAGES[amount]
    amount_usdt = int(amount)
    amount_cents = amount_usdt * 100

    prices = [LabeledPrice(label=f"{signals} сигналов", amount=amount_cents)]

    await context.bot.send_invoice(
        chat_id=chat_id,
        title="Покупка сигналов",
        description=f"{signals} сигналов за {amount_usdt} USDT",
        payload=f"user_{user_id}_{signals}",
        provider_token=CRYPTOBOT_PROVIDER_TOKEN,
        currency="USDT",
        prices=prices,
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False
    )
    logging.info(f"[💳 INVOICE SENT] user_id={user_id}, {signals} сигналов")


# === PreCheckout подтверждение ===
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


# === Обработка успешной оплаты ===
async def handle_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload

    try:
        _, user_id, signals = payload.split("_")
        user_id = int(user_id)
        signals = int(signals)

        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"signals_left": signals}, "$set": {"copy_enabled": True}},
            upsert=True
        )

        await update.message.reply_text(
            f"✅ Оплата прошла успешно!\nВам начислено {signals} сигналов."
        )
        logging.info(f"[✅ PAYMENT SUCCESS] user_id={user_id}, +{signals} сигналов")

    except Exception as e:
        logging.error(f"[❌ ERROR in successful_payment]: {e}")
        await update.message.reply_text("❌ Ошибка при обработке оплаты. Обратитесь в поддержку.")


# === Запуск бота ===
def run_payment_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, handle_successful_payment))

    logging.info("🚀 Бот оплаты запущен.")
    app.run_polling()


if __name__ == "__main__":
    run_payment_bot()