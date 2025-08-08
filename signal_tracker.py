from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client["bybit_bot"]
collection = db["active_signals"]

TTL_MINUTES = 5 

def is_duplicate_signal(symbol: str, side: str, entry_price: float) -> bool:
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=TTL_MINUTES)

    return collection.find_one({
        "symbol": symbol,
        "side": side,
        "entry_price": round(entry_price, 4),
        "timestamp": {"$gte": cutoff}
    }) is not None

def mark_signal_as_active(symbol: str, side: str, entry_price: float):
    collection.insert_one({
        "symbol": symbol,
        "side": side,
        "entry_price": round(entry_price, 4),
        "timestamp": datetime.utcnow()
    })
