import os
import requests
import json
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional
from openai import OpenAI


load_dotenv()


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('whatsapp_bot')


class WhatsAppBot:
    def __init__(self):
        self.instance_id = os.environ.get("INSTANCE_ID")
        self.api_token = os.environ.get("INSTANCE_TOKEN")
        self.base_url = f"https://api.green-api.com/waInstance{self.instance_id}"

        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key)
        self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

        if not all([self.instance_id, self.api_token, self.api_key]):
            raise ValueError("Не заданы переменные окружения: INSTANCE_ID/INSTANCE_TOKEN/OPENAI_API_KEY")
        
        
        self.system_prompt = """Ты — тёплый и компетентный бот-консультант по чат-ботам и автоматизации бизнеса в Казахстане.

КОНТЕКСТ И ПРАВИЛА:
• Пиши цены только в тенге (₸). Не используй рубли/доллары.
• Базовая разработка бота: от 150 000 ₸. Это стартовая цена, точная смета после уточнений.
• Если не уверен в фактах — задай уточняющий вопрос, не выдумывай.
• Отвечай кратко, дружелюбно, по делу. Добавляй 2–4 уместных эмодзи в ответ (но без перегруза).
• Оформляй ключевые пункты короткими абзацами или маркерами (•).
• Избегай канцеляризмов. Варируй формулировки, не начинай ответы одинаково.
• Если просят консультацию — одним сообщением попроси Имя, Компанию, Телефон, Задачу.
• Если спрашивают «что умеешь/продажи/CRM/цена» — отвечай предметно, с примерами, и легким CTA (например: «Показать пример?», «Записать на созвон?»).

ТЫ УМЕЕШЬ:
• Консультировать 24/7
• Автоматизировать заявки и заказы
• Интегрироваться с CRM (Битрикс24, amoCRM, HubSpot) через API (лиды, статусы, сделки, webhooks)
• Собирать обратную связь
• Делать уведомления и напоминания

ШАБЛОНЫ:
• Цена/стоимость → «Базовый WhatsApp-бот — от 150 000 ₸. Входит: сценарий, подключение API, базовая CRM-интеграция, 1 неделя поддержки. Нужна точная смета? Скажете нишу, цель, CRM и сроки — посчитаю 😊»
• CRM → «Интеграция через API: создаём лиды/сделки, статусы, webhooks. Хотите пример карты полей под вашу CRM?»
• Продажи → «Квалифицирую лидов, отвечаю на возражения, передаю менеджеру. Показать мини-скрипт под вашу нишу?»

Всегда держись тёплого, уверенного, разговорного тона и помни про KZT (₸)."""
        
        self.processed_messages = set() 
        self.history = {} 
        self.last_reply = {}  

    # УТИЛИТЫ: отправка/приём WhatsApp
    def clear_chat_history(self, chat_id: str):
        """Очистка истории чата для сброса контекста"""
        if chat_id in self.history:
            del self.history[chat_id]
        if chat_id in self.last_reply:
            del self.last_reply[chat_id]
        logger.info(f"История чата {chat_id} очищена")
    
    def send_message(self, chat_id: str, message: str) -> bool:
        """Отправка текстового сообщения"""
        url = f"{self.base_url}/sendMessage/{self.api_token}"
        payload = {"chatId": chat_id, "message": message}
        try:
            r = requests.post(url, json=payload, timeout=10)
            ok = r.status_code == 200
            if not ok:
                logger.error("Ошибка отправки: %s %s", r.status_code, r.text)
            return ok
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            return False

    def send_unique(self, chat_id: str, message: str) -> bool:
        """Не отправляем одно и то же подряд одному чату"""
        if self.last_reply.get(chat_id, "").strip() == message.strip():
            logger.info("Пропустили отправку: идентичный ответ подряд")
            return True
        ok = self.send_message(chat_id, message)
        if ok:
            self.last_reply[chat_id] = message
        return ok

    def get_notification(self) -> Optional[dict]:
        """Получение одного уведомления (Green API отдаёт по одному за вызов)"""
        url = f"{self.base_url}/receiveNotification/{self.api_token}"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                return data
            logger.error("receiveNotification %s %s", r.status_code, r.text)
            return None
        except Exception as e:
            logger.error(f"Ошибка получения уведомлений: {e}")
            return None

    def delete_notification(self, receipt_id: int) -> bool:
        """Удаление уведомления обязательно, иначе будет повтор"""
        url = f"{self.base_url}/deleteNotification/{self.api_token}/{receipt_id}"
        try:
            r = requests.delete(url, timeout=10)
            ok = r.status_code == 200
            if not ok:
                logger.error("deleteNotification %s %s", r.status_code, r.text)
            return ok
        except Exception as e:
            logger.error(f"Ошибка удаления уведомления: {e}")
            return False

    # LLM
    def get_openai_response(self, chat_id: str, user_message: str) -> str:
        """Ответ от OpenAI с использованием ИСТОРИИ диалога и мягких анти-повторов"""
        hist = self.history.setdefault(chat_id, [])
        hist.append({"role": "user", "content": user_message})

        window = hist[-12:]

        style_rules = (
            "Говори коротко, дружелюбно и по делу. Используй эмодзи умеренно (1–3 на ответ), "
            "без сухих канцеляризмов. Не повторяй один и тот же заголовок или вступление. "
            "Если пользователь просит записать на консультацию — собери: Имя, Компания, Телефон, Задача. "
            "Если нет каких-то полей — спроси их в одном сообщении, через компактную форму."
        )

        system = (
            self.system_prompt
            + "\n\nСТИЛЬ И ФОРМАТ:\n"
            + style_rules
            + "\n\nПРИМЕРЫ ОТВЕТОВ:\n"
            "— «Могу: отвечать 24/7, собирать заявки, создавать лиды в CRM и напоминать клиентам. Хотите пример сценария под ваш бизнес? »\n"
            "— «Да, помогаю продавать: квалифицирую лидов, отвечаю на возражения и передаю тёплых клиентов менеджеру. Нужны кейсы?»\n"
            "— «Готовы записать на консультацию. Заполните, пожалуйста:\n"
            "Имя: ...\nКомпания: ...\nТелефон: ...\nЗадача: ... »"
        )

        messages = [{"role": "system", "content": system}] + window

        try:
            resp = self.client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                max_tokens=350,
                temperature=0.8,
                top_p=0.9,
                frequency_penalty=0.6, 
                presence_penalty=0.5
            )
            answer = resp.choices[0].message.content.strip()
            hist.append({"role": "assistant", "content": answer})
            self.history[chat_id] = hist[-24:]  
            logger.info(f"🧠 GPT ответил: {answer[:80]}...")
            return answer
        except Exception as e:
            logger.error(f"Ошибка OpenAI: {e}")
            return "Простите, произошёл технический сбой. Попробуйте ещё раз через минуту 🙏"


    # БЫСТРАЯ МАРШРУТИЗАЦИЯ (без LLM)
    def route_intent(self, text: str) -> Optional[str]:
        t = (text or "").lower().strip()
        logger.info(f"Анализирую текст: '{t}'")

        hello_set = {"привет", "здравствуйте", "салам", "hi", "hello", "добрый день", "добрый вечер"}
        if t in hello_set or t.replace("!", "") in hello_set:
            return "Привет! Я помогу с ботами и автоматизацией. Расскажу, что умею, или сразу запишу на бесплатную консультацию. Что удобнее? 🙂"

        if any(kw in t for kw in ["записаться", "консультац", "созвон", "перезвон", "запишите меня", "appointment"]):
            form = (
                "Отлично! Запишу вас на бесплатную консультацию. Заполните, пожалуйста, кратко:\n"
                "Имя: \nКомпания: \nТелефон: \nЗадача (что автоматизировать): "
            )
            return form
        return None

    # Сохранение клиента
    def save_client_data(self, phone: str, data: dict) -> bool:
        try:
            filename = "client_records.json"
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    clients = json.load(f)
            else:
                clients = {}

            clients[phone] = {**data, 'recorded_at': datetime.now().isoformat(), 'status': 'new'}

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(clients, f, ensure_ascii=False, indent=2)
            logger.info(f"Записан клиент {phone}: {data.get('name', 'Без имени')}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")
            return False

    def extract_client_info(self, text: str) -> dict:
        info = {}
        for raw_line in text.split('\n'):
            line = raw_line.strip()
            low = line.lower()
            if 'имя:' in low or 'name:' in low:
                info['name'] = line.split(':', 1)[1].strip()
            elif 'компания:' in low or 'company:' in low:
                info['company'] = line.split(':', 1)[1].strip()
            elif 'телефон:' in low or 'phone:' in low:
                info['phone'] = line.split(':', 1)[1].strip()
            elif 'нужен бот для:' in low or 'бот для:' in low:
                info['bot_type'] = line.split(':', 1)[1].strip()
        return info

    # Основная обработка входящего сообщения
    def process_message(self, notification: dict):
        try:
            if not notification:
                return
            receipt_id = notification.get('receiptId')
            body = notification.get('body', {})
            if not body:
                return

            if body.get('typeWebhook') != 'incomingMessageReceived':
                if receipt_id:
                    self.delete_notification(receipt_id)
                return

            message_data = body.get('messageData', {})
            sender_data = body.get('senderData', {})

            # Текст сообщения
            if 'textMessageData' in message_data:
                message_text = message_data['textMessageData'].get('textMessage', '')
            else:
                if receipt_id:
                    self.delete_notification(receipt_id)
                return

            chat_id = sender_data.get('chatId', '')
            phone = sender_data.get('sender', '')

            if not message_text or not chat_id:
                if receipt_id:
                    self.delete_notification(receipt_id)
                return

            # Дедупликация
            message_id = message_data.get('idMessage')
            if message_id and message_id in self.processed_messages:
                if receipt_id:
                    self.delete_notification(receipt_id)
                return

            logger.info(f"Сообщение от {phone}: {message_text}")

            # Команда администратора
            if message_text.strip().startswith('/clients'):
                if phone in {"+77776463138", "77776463138"}:
                    self.handle_clients_command(chat_id)
                else:
                    self.send_message(chat_id, "У вас нет доступа к этой команде")
                if message_id:
                    self.processed_messages.add(message_id)
                if receipt_id:
                    self.delete_notification(receipt_id)
                return

            if any(k in message_text.lower() for k in ['имя:', 'компания:', 'телефон:', 'name:', 'company:', 'phone:', 'задач']):
                client_info = self.extract_client_info(message_text)

                if 'задача' not in client_info and 'бот для' in message_text.lower():
                    client_info['bot_type'] = message_text.split(':', 1)[-1].strip()

                need = []
                if not client_info.get('name'):     need.append("Имя")
                if not client_info.get('company'):  need.append("Компания")
                if not client_info.get('phone'):    need.append("Телефон")
                if not client_info.get('bot_type'): need.append("Задача")

                if need:
                    ask = "Почти всё! Не хватает: " + ", ".join(need) + ".\nПришлите одним сообщением в формате:\nИмя: ...\nКомпания: ...\nТелефон: ...\nЗадача: ..."
                    self.send_message(chat_id, ask)
                else:
                    if self.save_client_data(phone, client_info):
                        resp = (
                            "✅ Записал вас на бесплатную консультацию!\n\n"
                            f"👤 Имя: {client_info.get('name')}\n"
                            f"🏢 Компания: {client_info.get('company')}\n"
                            f"📱 Телефон: {client_info.get('phone')}\n"
                            f"🧩 Задача: {client_info.get('bot_type')}\n\n"
                            "Свяжемся в ближайшее время. Предпочтительнее звонок или WhatsApp? 🙂"
                        )
                        self.send_message(chat_id, resp)
                if message_id:
                    self.processed_messages.add(message_id)
                if receipt_id:
                    self.delete_notification(receipt_id)
                return
                    
                    
            if message_text.strip() == '/reset':
                if phone in {"+77776463138", "77776463138"}:
                    self.clear_chat_history(chat_id)
                    self.send_message(chat_id, "✅ История чата очищена")
                if message_id:
                    self.processed_messages.add(message_id)
                if receipt_id:
                    self.delete_notification(receipt_id)
                return

            quick = self.route_intent(message_text)
            if quick:
                self.send_message(chat_id, quick)
                if message_id:
                    self.processed_messages.add(message_id)
                if receipt_id:
                    self.delete_notification(receipt_id)
                return

            response = self.get_openai_response(chat_id, message_text)
            self.send_message(chat_id, response)

            if message_id:
                self.processed_messages.add(message_id)
            if receipt_id:
                self.delete_notification(receipt_id)

        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            rid = notification.get('receiptId') if notification else None
            if rid:
                self.delete_notification(rid)

    # /clients команда
    def handle_clients_command(self, chat_id: str):
        try:
            filename = "client_records.json"
            if not os.path.exists(filename):
                self.send_message(chat_id, "📭 Записей пока нет")
                return

            with open(filename, 'r', encoding='utf-8') as f:
                clients = json.load(f)

            if not clients:
                self.send_message(chat_id, "📭 Записей пока нет")
                return

            recent = list(clients.items())[-3:]
            response_lines = ["📋 Последние записи:\n"]
            for phone, data in recent:
                response_lines.append(
                    (
                        f"📱 {phone}\n"
                        f"👤 {data.get('name', 'Не указано')}\n"
                        f"🏢 {data.get('company', 'Не указано')}\n"
                        f"🤖 {data.get('bot_type', 'Не указано')}\n"
                        f"📅 {data.get('recorded_at', '').split('T')[0]}\n"
                    )
                )
            self.send_message(chat_id, "\n".join(response_lines))
        except Exception as e:
            self.send_message(chat_id, f"Ошибка: {e}")

    # Главный цикл
    def run(self):
        logger.info("🤖 Бот запущен!")

        try:
            settings_url = f"{self.base_url}/setSettings/{self.api_token}"
            settings = {"incomingWebhook": "yes", "pollMessageWebhook": "yes"}
            requests.post(settings_url, json=settings, timeout=10)
        except Exception as e:
            logger.warning(f"Не удалось применить setSettings: {e}")

        while True:
            try:
                notification = self.get_notification()
                if notification:
                    self.process_message(notification)
                else:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("⛔ Бот остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в главном цикле: {e}")
                time.sleep(5)


if __name__ == "__main__":
    try:
        bot = WhatsAppBot()
        bot.run()
    except Exception as e:
        print(f"Ошибка запуска: {e}")
        print("Проверьте переменные окружения в .env файле: INSTANCE_ID, INSTANCE_TOKEN, OPENAI_API_KEY, (опц.) OPENAI_MODEL")


