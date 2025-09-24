import os
import requests
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Получаем реальные значения из .env файла
INSTANCE_ID = os.environ.get("INSTANCE_ID")
TOKEN = os.environ.get("INSTANCE_TOKEN")
API_URL = "https://api.green-api.com"

print(f"Проверяем инстанс: {INSTANCE_ID}")
print(f"Токен: {TOKEN[:10]}...")

# Правильный URL с реальными значениями
url = f"{API_URL}/waInstance{INSTANCE_ID}/receiveNotification/{TOKEN}"

print(f"URL: {url}")

# Делаем запрос
response = requests.get(url)

print(f"Статус ответа: {response.status_code}")
print(f"Ответ: {response.text}")

# Проверяем JSON
try:
    json_response = response.json()
    print(f"JSON ответ: {json_response}")
    
    if json_response is None:
        print("❌ Уведомлений нет (null)")
    else:
        print("✅ Есть уведомления!")
        print(json_response)
except:
    print("❌ Ошибка парсинга JSON")

# Дополнительно проверим статус инстанса
print("\n--- Проверка статуса инстанса ---")
status_url = f"{API_URL}/waInstance{INSTANCE_ID}/getStateInstance/{TOKEN}"
status_response = requests.get(status_url)
print(f"Статус инстанса: {status_response.json()}")