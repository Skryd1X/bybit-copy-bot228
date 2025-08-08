
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

# 🔐 Шифрование временно отключено (TODO: включить в проде)
def encrypt(text):
    return text

def decrypt(token):
    return token

# 🔗 Подключение к MongoDB
MONGO_URI = "mongodb+srv://signalsbybitbot:ByBitSignalsBot%40@cluster0.ucqufe4.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)

# 📂 Базы данных
signal_db = client["signal_bot"]
bybit_db = client["bybit"]
subscribers_db = client["bybit_bot"]

# 📁 Коллекции
users = signal_db["users"]
history = signal_db["history"]
clients = bybit_db["clients"]
subscribers = subscribers_db["subscribers"]

# 📌 Индексы
users.create_index("user_id", unique=True)
history.create_index("user_id")
history.create_index("timestamp")
subscribers.create_index("chat_id", unique=True)

# ⏰ Московское время
MSK = timezone(timedelta(hours=3))

# 👤 Получение одного пользователя
def get_user(user_id):
    user = users.find_one({"user_id": user_id})
    if user:
        user["fixed_usdt"] = user.get("fixed_usdt", 10)
        user["account_type"] = user.get("account_type", "UNIFIED")
        if "api_key" in user and "api_secret" in user:
            try:
                user["api_key"] = decrypt(user["api_key"])
                user["api_secret"] = decrypt(user["api_secret"])
            except:
                user["api_key"] = ""
                user["api_secret"] = ""
    return user

# 👥 Получение всех пользователей с copy_enabled=True и активными ключами
def get_all_users():
    all_users = list(users.find({
        "copy_enabled": True,
        "api_key": {"$exists": True, "$ne": None},
        "api_secret": {"$exists": True, "$ne": None},
        "signals_left": {"$gt": 0}
    }))
    for user in all_users:
        user["fixed_usdt"] = user.get("fixed_usdt", 10)
        user["account_type"] = user.get("account_type", "UNIFIED")
        try:
            user["api_key"] = decrypt(user["api_key"])
            user["api_secret"] = decrypt(user["api_secret"])
        except:
            user["api_key"] = ""
            user["api_secret"] = ""
    return all_users

# 💾 Сохранение API-ключей
def save_api_keys(user_id, api_key, api_secret, account_type="UNIFIED"):
    now_msk = datetime.now(MSK)
    users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "api_key": encrypt(api_key),
                "api_secret": encrypt(api_secret),
                "account_type": account_type,
                "created_at": now_msk
            },
            "$setOnInsert": {
                "copy_enabled": False,
                "lang": "ru",
                "awaiting": None,
                "fixed_usdt": 10,
                "signals_left": 0
            }
        },
        upsert=True
    )
    clients.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "api_key": encrypt(api_key),
                "api_secret": encrypt(api_secret),
                "account_type": account_type,
                "enabled": True,
                "fixed_usdt": 10
            }
        },
        upsert=True
    )

# ✏️ Обновление данных пользователя
def update_user(user_id, fields: dict):
    users.update_one({"user_id": user_id}, {"$set": fields})

# ❌ Удаление ключей
def delete_api(user_id):
    users.update_one(
        {"user_id": user_id},
        {"$unset": {"api_key": "", "api_secret": "", "account_type": ""}, "$set": {"copy_enabled": False}}
    )
    clients.update_one(
        {"user_id": user_id},
        {"$unset": {"api_key": "", "api_secret": "", "account_type": ""}, "$set": {"enabled": False}}
    )

# 📈 Лог сделки
def log_trade(user_id, symbol, side, entry, size, tp=0, sl=0, exit_price=0):
    history.insert_one({
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "size": size,
        "tp": tp,
        "sl": sl,
        "exit": exit_price,
        "timestamp": datetime.utcnow()
    })

# 🚪 Лог закрытия сделки (обновлённая версия)
def log_close_trade(user_id, symbol, side, entry_price, qty, exit_price):
    history.insert_one({
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "entry": entry_price,
        "size": qty,
        "tp": 0,
        "sl": 0,
        "exit": exit_price,
        "timestamp": datetime.utcnow()
    })

# 📅 Сделки за сегодня
def get_today_trades(user_id):
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return list(history.find({
        "user_id": user_id,
        "timestamp": {"$gte": start}
    }))

# 🧮 Статистика
def save_stats(user_id, symbol, side, price, qty):
    history.insert_one({
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "price": price,
        "qty": qty,
        "timestamp": datetime.utcnow()
    })

def get_stats(user_id):
    return list(history.find({"user_id": user_id}).sort("timestamp", -1).limit(10))

# ✅ Привязка chat_id
def add_chat_id(chat_id: int, user_id: int = None):
    if not subscribers.find_one({"chat_id": chat_id}):
        subscribers.insert_one({"chat_id": chat_id})
    if user_id:
        users.update_one(
            {"user_id": user_id},
            {"$set": {"chat_id": chat_id}},
            upsert=True
        )

# 📬 Получение всех chat_id
def get_all_chat_ids():
    return [doc["chat_id"] for doc in subscribers.find()]
