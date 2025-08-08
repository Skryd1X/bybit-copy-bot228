from flask import Flask, request, jsonify
from pymongo import MongoClient
import logging
import json

# === Flask-приложение ===
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === MongoDB ===
MONGO_URI = "mongodb+srv://signalsbybitbot:ByBitSignalsBot%40@cluster0.ucqufe4.mongodb.net/?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
users_collection = client["signal_bot"]["users"]

# === Пакеты сигналов ===
SIGNAL_PACKAGES = {
    "15": 15,
    "30": 35,
    "50": 60
}

# === Webhook от CryptoBot ===
@app.route("/cryptobot-webhook", methods=["POST"])
def cryptobot_webhook():
    try:
        data = request.json
        logging.info(f"[📩 WEBHOOK] Получены данные: {data}")

        status = data.get("status")
        payload = data.get("payload")

        if status != "paid" or not payload:
            return jsonify({"status": "ignored"}), 200

        # Пример payload: user123456_15_1f23a...
        parts = payload.split("_")
        if len(parts) < 3:
            return jsonify({"error": "invalid payload"}), 400

        user_id = int(parts[0].replace("user", ""))
        signals = int(parts[1])

        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"signals_left": signals}, "$set": {"copy_enabled": True}},
            upsert=True
        )

        logging.info(f"[✅] Начислено {signals} сигналов пользователю {user_id}")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"[❌ Ошибка]: {e}")
        return jsonify({"error": "server error"}), 500

# === Запуск Flask-сервера ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8888)
