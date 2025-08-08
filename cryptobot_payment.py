from dotenv import load_dotenv
import os
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import logging
from pymongo import MongoClient
import requests

# === Настройки ===
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client["signal_bot"]
users_collection = db["users"]
invoices_collection = db["invoices"]

# === Тарифы: кол-во сигналов, цена в USDT
PACKAGE_MAP = {
    "buy_15": (15, 15),
    "buy_30": (35, 30),
    "buy_50": (60, 50),
}

# === Получить язык пользователя
def get_user_lang(user_id: int) -> str:
    user = users_collection.find_one({"user_id": user_id})
    return user.get("lang", "ru") if user else "ru"

# === Создание инвойса через CryptoBot
def create_invoice(amount: float, asset: str, description: str, hidden_payload: str) -> dict:
    url = f"{CRYPTOBOT_API_URL}/createInvoice"
    headers = {
        "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
    }
    data = {
        "asset": asset,
        "amount": str(amount),
        "description": description,
        "hidden_message": "Thanks for your payment!",
        "hidden_payload": hidden_payload,
        "allow_comments": False,
        "allow_anonymous": False
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        result = response.json()
        logging.info(f"CryptoBot invoice response: {result}")
        return result
    except Exception as e:
        logging.error(f"Invoice creation failed: {e}")
        return {"ok": False}

# === Обработка покупки: генерация инвойса и кнопки ===
async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    tariff = query.data

    if tariff not in PACKAGE_MAP:
        await query.edit_message_text("❌ Неверный тариф.")
        return

    signals, amount = PACKAGE_MAP[tariff]
    lang = get_user_lang(user_id)
    payload = f"user_{user_id}_{signals}"
    description = f"{signals} сигналов за {amount} USDT"

    invoice_response = create_invoice(
        amount=amount,
        asset="USDT",
        description=description,
        hidden_payload=payload
    )

    if not invoice_response.get("ok"):
        await query.edit_message_text("❌ Ошибка при создании счёта. Попробуйте позже.")
        logging.error(f"Invoice creation failed: {invoice_response}")
        return

    invoice_url = invoice_response["result"]["pay_url"]
    invoice_id = invoice_response["result"]["invoice_id"]

    invoices_collection.insert_one({
        "invoice_id": invoice_id,
        "user_id": user_id,
        "signals": signals,
        "status": "pending",
        "payload": payload
    })

    text = (
        f"💰 *Счёт создан!*\n"
        f"💵 Сумма: *{amount:.2f} USDT*\n"
        f"📦 Тариф: *{signals} сигналов*\n\n"
        f"Нажмите кнопку ниже для оплаты."
    ) if lang == "ru" else (
        f"💰 *Invoice created!*\n"
        f"💵 Amount: *{amount:.2f} USDT*\n"
        f"📦 Package: *{signals} signals*\n\n"
        f"Click the button below to pay."
    )
    pay_button = "💳 Оплатить" if lang == "ru" else "💳 Pay"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(pay_button, url=invoice_url)],
        [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_invoice_{invoice_id}")]
    ])

    try:
        await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer("⌛ Статус оплаты не изменился.", show_alert=True)
        else:
            raise e

# === Обработка кнопки "Проверить оплату" ===
async def check_invoice_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    invoice_id = data.replace("check_invoice_", "")
    url = f"{CRYPTOBOT_API_URL}/getInvoices?invoice_ids={invoice_id}"
    headers = {
        "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
    }

    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        logging.info(f"Invoice status response: {data}")
    except Exception as e:
        logging.error(f"Failed to check invoice status: {e}")
        await query.edit_message_text("❌ Не удалось проверить оплату. Попробуйте позже.")
        return

    if not data.get("ok"):
        await query.edit_message_text("❌ Не удалось проверить оплату. Попробуйте позже.")
        return

    items = data["result"].get("items", [])
    if not items:
        await query.edit_message_text("❌ Счёт не найден.")
        return

    invoice = items[0]
    status = invoice["status"]
    invoice_url = invoice["pay_url"]

    if status == "paid":
        invoice_doc = invoices_collection.find_one({"invoice_id": int(invoice_id)})
        if not invoice_doc:
            await query.edit_message_text("❌ Счёт не найден в базе.")
            return

        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"signals_left": invoice_doc["signals"]}, "$set": {"copy_enabled": True}},
            upsert=True
        )
        invoices_collection.update_one({"invoice_id": int(invoice_id)}, {"$set": {"status": "paid"}})

        await query.edit_message_text(f"✅ Оплата подтверждена! Вам начислено {invoice_doc['signals']} сигналов.")

        # 💬 Отправка отдельного сообщения пользователю
        try:
            lang = get_user_lang(user_id)
            text = (
                f"🎉 *Оплата прошла успешно!*\n"
                f"🔓 Вам начислено *{invoice_doc['signals']}* сигналов.\n"
                f"Спасибо за покупку и приятной торговли! 📈"
            ) if lang == "ru" else (
                f"🎉 *Payment successful!*\n"
                f"🔓 You have received *{invoice_doc['signals']}* signals.\n"
                f"Thank you for your purchase and happy trading! 📈"
            )
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            logging.info(f"📩 Уведомление об оплате отправлено пользователю {user_id}")
        except Exception as e:
            logging.warning(f"⚠️ Ошибка при отправке уведомления об оплате: {e}")

    elif status == "expired":
        await query.edit_message_text("❌ Счёт просрочен.")

    else:
        invoice_doc = invoices_collection.find_one({"invoice_id": int(invoice_id)})
        if not invoice_doc:
            await query.edit_message_text("❌ Счёт не найден в базе.")
            return

        signals = invoice_doc["signals"]
        amount = {
            15: 15, 35: 30, 60: 50
        }.get(signals, 0)

        lang = get_user_lang(user_id)
        text = (
            f"⌛ *Оплата пока не подтверждена...*\n"
            f"💵 Сумма: *{amount} USDT*\n"
            f"📦 Тариф: *{signals} сигналов*\n\n"
            f"Попробуйте позже или завершите оплату."
        ) if lang == "ru" else (
            f"⌛ *Payment not confirmed yet...*\n"
            f"💵 Amount: *{amount} USDT*\n"
            f"📦 Package: *{signals} signals*\n\n"
            f"Try again later or complete the payment."
        )
        pay_button = "💳 Оплатить" if lang == "ru" else "💳 Pay"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(pay_button, url=invoice_url)],
            [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_invoice_{invoice_id}")]
        ])

        try:
            await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=keyboard)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                await query.answer("⌛ Статус оплаты не изменился.", show_alert=True)
            else:
                raise e