from database import db
key = input("Вставьте Groq ключ: ")
db.save_settings({'groq_api_key': key.strip()})
print("Сохранено:", db.get_settings().get('groq_api_key', '')[:15])
