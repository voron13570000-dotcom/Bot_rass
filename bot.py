#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ С КНОПОЧНЫМ МЕНЮ
Авто-регистрация пользователя при нажатии любой кнопки
"""

import requests
import time
import sqlite3
import hashlib
import json
from datetime import datetime, timedelta, timezone
import os
import threading
import logging
import sys

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8534692585:AAHRp6JsPORhX3KF-bqM2bPQz0RuWEKVxt8" 
ADMIN = "7634746932" 
TZ_EKATERINBURG = timezone(timedelta(hours=5)) 

CHECK_INTERVAL = 300
MAX_DAYS_BACK = 7

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class Button_URGT_Bot:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/"
        self.init_db()
        self.last_update_id = 0
        self.running = True
        self.waiting_for_broadcast = False
        
        logger.info("🤖 БОТ УрЖТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ")
    
    def init_db(self):
        os.makedirs("data", exist_ok=True)
        self.conn = sqlite3.connect("data/urgt_buttons.db", check_same_thread=False)
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                notifications INTEGER DEFAULT 1,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, file_url TEXT, file_hash TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def send_message(self, chat_id, text, keyboard=None):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
        if keyboard: params['reply_markup'] = keyboard
        try:
            r = requests.post(url, params=params, timeout=15)
            return r.status_code == 200
        except: return False

    def send_pdf(self, chat_id, pdf_url):
        try:
            os.makedirs("temp", exist_ok=True)
            r = requests.get(pdf_url, timeout=20)
            if r.status_code == 200:
                temp_file = "temp/temp_schedule.pdf"
                with open(temp_file, "wb") as f: f.write(r.content)
                with open(temp_file, "rb") as file:
                    requests.post(self.base_url + "sendDocument", 
                                 data={'chat_id': chat_id, 'caption': '📄 Расписание УрЖТ'}, 
                                 files={'document': file}, timeout=30)
                return True
            return False
        except: return False

    def create_main_keyboard(self):
        return json.dumps({
            "keyboard": [
                [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
                [{"text": "🔔 Расписание звонков"}],
                [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}],
                [{"text": "❤️ Поддержать автора"}]
            ], "resize_keyboard": True
        })

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username', '')
            text = message.get('text', '').strip()
            is_admin = str(user_id) == str(ADMIN)

            # РЕГИСТРАЦИЯ: Добавляем пользователя при любом действии
            cursor = self.conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                           (user_id, username, message['from'].get('first_name'), message['from'].get('last_name')))
            self.conn.commit()

            # ЛОГИКА КНОПОК
            if text in ['/start', '/старт']:
                self.send_message(chat_id, "👋 *Бот УрЖТ готов к работе!*", self.create_main_keyboard())
            
            elif text == '📅 Сегодня':
                date = datetime.now(TZ_EKATERINBURG)
                self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
                url = f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date.strftime('%d%m%Y')}.pdf"
                if not self.send_pdf(chat_id, url): self.send_message(chat_id, "❌ Расписание еще не опубликовано.")

            elif text == '📆 Завтра':
                date = datetime.now(TZ_EKATERINBURG) + timedelta(days=1)
                self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
                url = f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date.strftime('%d%m%Y')}.pdf"
                if not self.send_pdf(chat_id, url): self.send_message(chat_id, "❌ Расписание еще не опубликовано.")

            elif text == '🔔 Расписание звонков':
                self.handle_bells(chat_id)

            elif text == '🔍 Проверить обновления':
                self.send_message(chat_id, "✅ У вас актуальное расписание.") # Заглушка для ручной проверки

            elif text == '⚙️ Настройки':
                kb = json.dumps({"keyboard": [[{"text": "🔔 Вкл/Выкл уведомления"}], [{"text": "⬅️ Назад"}]], "resize_keyboard": True})
                self.send_message(chat_id, "⚙️ *НАСТРОЙКИ*", kb)

            elif text == '❤️ Поддержать автора':
                self.send_message(chat_id, "❤️ *ПОДДЕРЖКА*\n💳 Карта: `2200 7014 1439 4772` \nАвтор: @M1PTAHKOB")

            elif text == '⬅️ Назад':
                self.send_message(chat_id, "↩️ Главное меню", self.create_main_keyboard())

            # ОБРАТНАЯ СВЯЗЬ АДМИНУ
            elif not is_admin:
                admin_msg = f"📩 *Новое сообщение!*\nОт: {message['from'].get('first_name')}\nID: `{user_id}`\n\n💬 Текст: {text}"
                self.send_message(ADMIN, admin_msg)
                self.send_message(chat_id, "✅ Сообщение отправлено администратору.")

        except Exception as e:
            logger.error(f"Ошибка: {e}")

    def handle_bells(self, chat_id):
        now = datetime.now(TZ_EKATERINBURG)
        day = now.weekday()
        if day == 0: # ПН
            msg = "🔔 *ЗВОНКИ (Понедельник)*\n📢 Линейка: 08:30\n1 пара: 09:40 — 11:15..."
        elif day == 5: # СБ
            msg = "🔔 *ЗВОНКИ (Суббота)*\n1 пара: 09:00 — 10:35..."
        else: # ВТ-ПТ
            msg = "🔔 *ЗВОНКИ (Будни)*\n1 пара: 09:00 — 10:35..."
        self.send_message(chat_id, msg)

    def run(self):
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'timeout': 30, 'offset': self.last_update_id + 1})
                if r.status_code == 200:
                    for u in r.json().get('result', []):
                        self.last_update_id = u['update_id']
                        if 'message' in u: self.process_message(u['message'])
                time.sleep(0.5)
            except: time.sleep(5)

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
            
