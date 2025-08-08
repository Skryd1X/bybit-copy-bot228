# wipe_mongo_collections.py
from pymongo import MongoClient
import sys

MONGO_URI = "mongodb+srv://signalsbybitbot:ByBitSignalsBot%40@cluster0.ucqufe4.mongodb.net/?retryWrites=true&w=majority"

# Какие базы чистим (только их, остальные не трогаем)
TARGET_DATABASES = ["signal_bot", "bybit_bot", "побит"]

# Если хочешь пропустить какие-то коллекции внутри баз — укажи тут
SKIP_COLLECTIONS = set([
    # пример: "users"
])

def main():
    client = MongoClient(MONGO_URI)
    to_clean = []  # список (db_name, coll_name)

    print("🧹 План очистки MongoDB (удаляем документы, коллекции остаются):\n")

    for db_name in TARGET_DATABASES:
        db = client[db_name]
        try:
            colls = db.list_collection_names()
        except Exception as e:
            print(f"⚠️ Не удалось получить список коллекций для базы '{db_name}': {e}")
            continue

        if not colls:
            print(f"— База '{db_name}' пуста (коллекций нет).")
            continue

        print(f"База: {db_name}")
        for coll_name in colls:
            if coll_name in SKIP_COLLECTIONS:
                print(f"  • {coll_name}  (пропущена)")
                continue
            cnt = db[coll_name].count_documents({})
            print(f"  • {coll_name}: {cnt} документов")
            to_clean.append((db_name, coll_name))
        print()

    if not to_clean:
        print("✅ Нечего чистить — подходящих коллекций не найдено.")
        return

    confirm = input("❓ Подтвердить удаление ВСЕХ документов во всех перечисленных коллекциях? (yes/NO): ").strip().lower()
    if confirm != "yes":
        print("⏹ Отменено.")
        return

    # Удаляем документы
    for db_name, coll_name in to_clean:
        db = client[db_name]
        coll = db[coll_name]
        try:
            result = coll.delete_many({})
            print(f"🗑 {db_name}.{coll_name}: удалено {result.deleted_count} документов")
        except Exception as e:
            print(f"❌ Ошибка при очистке {db_name}.{coll_name}: {e}")

    print("\n✅ Готово. Структура баз/коллекций сохранена, документы удалены.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹ Прервано пользователем.")
        sys.exit(1)
