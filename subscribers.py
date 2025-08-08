from pymongo import MongoClient
from datetime import datetime

# 🔗 Подключение к MongoDB
MONGO_URI = "mongodb+srv://signalsbybitbot:ByBitSignalsBot%40@cluster0.ucqufe4.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)

# 📂 Базы данных и коллекции
db = client["bybit_bot"]
subscribers_collection = db["subscribers"]

signal_db = client["signal_bot"]
users_collection = signal_db["users"]

# 📌 Добавление chat_id и связь с user_id (без сброса настроек)
def add_chat_id(chat_id: int, user_id: int = None):
    # Добавляем chat_id в список подписчиков, если его ещё нет
    if not subscribers_collection.find_one({"chat_id": chat_id}):
        subscribers_collection.insert_one({"chat_id": chat_id})

    # Привязываем chat_id к user_id без перезаписи существующих настроек
    if user_id:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "chat_id": chat_id
                },
                "$setOnInsert": {
                    "copy_enabled": False,
                    "fixed_usdt": 10,
                    "lang": "ru",
                    "created_at": datetime.utcnow(),
                    "signals_left": 0,
                    "awaiting": None
                }
            },
            upsert=True
        )

# 📬 Получение всех подписанных chat_id
def get_all_chat_ids():
    return [doc["chat_id"] for doc in subscribers_collection.find()]

# ❌ Удаление chat_id
def remove_chat_id(chat_id: int):
    subscribers_collection.delete_one({"chat_id": chat_id})
    users_collection.update_many({"chat_id": chat_id}, {"$unset": {"chat_id": ""}})

# 🔍 Проверка подписки
def is_subscribed(chat_id: int) -> bool:
    return subscribers_collection.find_one({"chat_id": chat_id}) is not None

# 👤 Получение пользователя
def get_user(user_id: int) -> dict:
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "lang": "ru",
            "awaiting": None,
            "copy_enabled": False,
            "signals_left": 0,
            "fixed_usdt": 10,
            "created_at": datetime.utcnow()
        }
        users_collection.insert_one(user)
    return user

# ✏️ Обновление пользователя (частичное обновление)
def update_user(user_id: int, data: dict):
    users_collection.update_one({"user_id": user_id}, {"$set": data}, upsert=True)

# 🔐 Сохранение API ключей (включаем автокопирование при добавлении ключей)
def save_api_keys(user_id: int, api_key: str, api_secret: str, account_type: str = "UNIFIED"):
    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "api_key": api_key,
                "api_secret": api_secret,
                "account_type": account_type,
                "copy_enabled": True
            }
        },
        upsert=True
    )
