#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ С КНОПОЧНЫМ МЕНЮ И РАССЫЛКОЙ
Автоматическое переключение расписания звонков: ПН, ВТ-ПТ, СБ.
"""

import requests
import time
import sqlite3
import hashlib
import json
from datetime import datetime, timedelta
import os
import threading
import logging
import sys

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8534692585:AAHRp6JsPORhX3KF-bqM2bPQz0RuWEKVxt8" 
ADMIN = "7634746932" 

CHECK_INTERVAL = 300
MAX_DAYS_BACK = 7

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('urgt_bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class Button_URGT_Bot:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/"
        self.init_db()
        self.last_update_id = 0
        self.running = True
        self.waiting_for_broadcast = False
        
        logger.info("=" * 60)
        logger.info("🤖 БОТ УрЖТ ЗАПУЩЕН")
        logger.info(f"👑 Администратор ID: {ADMIN}")
        logger.info("=" * 60)
    
    def init_db(self):
        try:
            os.makedirs("data", exist_ok=True)
            self.conn = sqlite3.connect("data/urgt_buttons.db", check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    notifications INTEGER DEFAULT 1,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    file_url TEXT,
                    file_hash TEXT,
                    file_size INTEGER,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notified INTEGER DEFAULT 0,
                    UNIQUE(date, file_hash)
                )
            """)
            self.conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка БД: {e}")
            raise

    def send_message(self, chat_id, text, keyboard=None, parse_mode='Markdown'):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode, 'disable_web_page_preview': True}
        if keyboard: params['reply_markup'] = keyboard
        try:
            response = requests.post(url, params=params, timeout=15)
            if response.status_code != 200 and "can't parse entities" in response.text:
                params.pop('parse_mode')
                response = requests.post(url, params=params, timeout=15)
            return response.status_code == 200
        except: return False

    def send_pdf(self, chat_id, pdf_url):
        try:
            os.makedirs("temp", exist_ok=True)
            response = requests.get(pdf_url, timeout=20, stream=True)
            if response.status_code == 200:
                temp_file = "temp/temp_schedule.pdf"
                with open(temp_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
                with open(temp_file, "rb") as file:
                    requests.post(self.base_url + "sendDocument", 
                                 data={'chat_id': chat_id, 'caption': '📄 Расписание УрЖТ'}, 
                                 files={'document': file}, timeout=30)
                if os.path.exists(temp_file): os.remove(temp_file)
                return True
            return False
        except: return False

    def get_pdf_url(self, target_date):
        date_str = target_date.strftime("%d%m%Y")
        return f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date_str}.pdf"

    def create_main_keyboard(self):
        return json.dumps({
            "keyboard": [
                [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
                [{"text": "🔔 Расписание звонков"}],
                [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}],
                [{"text": "ℹ️ Помощь"}, {"text": "👤 Мой профиль"}],
                [{"text": "❤️ Поддержать автора"}]
            ], "resize_keyboard": True
        })

    def create_settings_keyboard(self, is_admin=False):
        buttons = [[{"text": "🔔 Вкл/Выкл уведомления"}]]
        if is_admin: buttons.append([{"text": "📢 Рассылка всем"}])
        buttons.extend([[{"text": "📊 Статистика бота"}], [{"text": "⬅️ Назад"}]])
        return json.dumps({"keyboard": buttons, "resize_keyboard": True})

    def create_back_keyboard(self):
        return json.dumps({"keyboard": [[{"text": "⬅️ Назад"}]], "resize_keyboard": True})

    def handle_bells(self, chat_id):
        now = datetime.now()
        day_of_week = now.weekday() # 0 - ПН, 1 - ВТ... 5 - СБ, 6 - ВС

        if day_of_week == 0: # ПОНЕДЕЛЬНИК (Линейка + КЧ)
            bells_text = (
                "🔔 *ЗВОНКИ УрЖТ (Понедельник)*\n"
                "📍 _г. Екатеринбург_\n\n"
                "📢 *Линейка:* 08:30 — 08:40\n"
                "🏫 *Классный час:* 08:45 — 09:30\n\n"
                "1️⃣ *1 пара:* 09:40 — 10:25 | 10:30 — 11:15\n"
                "2️⃣ *2 пара:* 11:25 — 12:10 | 12:15 — 13:00\n"
                "🍱 *Обед:* 13:00 — 13:40\n"
                "3️⃣ *3 пара:* 13:40 — 14:25 | 14:30 — 15:15\n"
                "☕️ *Перерыв:* 15:15 — 15:35\n"
                "4️⃣ *4 пара:* 15:35 — 16:20 | 16:25 — 17:10\n"
                "5️⃣ *5 пара:* 17:20 — 18:05 | 18:10 — 18:55\n"
                "6️⃣ *6 пара:* 19:05 — 19:50 | 19:55 — 20:40"
            )
        elif day_of_week == 5: # СУББОТА
            bells_text = (
                "🔔 *ЗВОНКИ УрЖТ (Суббота)*\n"
                "📍 _г. Екатеринбург_\n\n"
                "1️⃣ *1 пара:* 09:00 — 09:45 | 09:50 — 10:35\n"
                "2️⃣ *2 пара:* 10:45 — 11:30 | 11:35 — 12:20\n"
                "🍱 *Обед:* 12:20 — 12:40\n"
                "3️⃣ *3 пара:* 12:40 — 13:25 | 13:30 — 14:15\n"
                "4️⃣ *4 пара:* 14:25 — 15:10 | 15:15 — 16:00"
            )
        else: # ВТОРНИК - ПЯТНИЦА
            bells_text = (
                "🔔 *ЗВОНКИ УрЖТ (Вторник–Пятница)*\n"
                "📍 _г. Екатеринбург_\n\n"
                "1️⃣ *1 пара:* 09:00 — 09:45 | 09:50 — 10:35\n"
                "2️⃣ *2 пара:* 10:45 — 11:30 | 11:35 — 12:20\n"
                "🍱 *Обед:* 12:20 — 13:00\n"
                "3️⃣ *3 пара:* 13:00 — 13:40 | 13:45 — 14:30\n"
                "☕️ *Перерыв:* 14:30 — 14:50\n"
                "4️⃣ *4 пара:* 14:50 — 15:35 | 15:40 — 16:25\n"
                "5️⃣ *5 пара:* 16:35 — 17:20 | 17:25 — 18:10\n"
                "6️⃣ *6 пара:* 18:20 — 19:05 | 19:10 — 19:55"
            )
        self.send_message(chat_id, bells_text)

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username', '')
            text = message.get('text', '').strip()
            is_admin = str(user_id) == str(ADMIN)

            if is_admin and text == '/users':
                cursor = self.conn.cursor()
                cursor.execute("SELECT user_id, username, first_name FROM users")
                users_list = cursor.fetchall()
                report = "👥 *Список пользователей:*\n\n"
                for u in users_list: report += f"`{u[0]}` | @{u[1]} | {u[2]}\n"
                self.send_message(chat_id, report[:4000])
                return

            if is_admin and text.startswith('/send'):
                parts = text.split(maxsplit=2)
                if len(parts) == 3:
                    self.send_message(parts[1], f"✉️ *Личное сообщение от администратора:*\n\n{parts[2]}")
                return

            if text in ['/start', '/старт']:
                cursor = self.conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                               (user_id, username, message['from'].get('first_name'), message['from'].get('last_name')))
                self.conn.commit()
                self.send_message(chat_id, "👋 *Бот УрЖТ готов к работе!*", self.create_main_keyboard())
            elif text == '📅 Сегодня': self.handle_today(chat_id)
            elif text == '📆 Завтра': self.handle_tomorrow(chat_id)
            elif text == '🔔 Расписание звонков': self.handle_bells(chat_id)
            elif text == '🔍 Проверить обновления': self.handle_check_updates(chat_id)
            elif text == '⚙️ Настройки': self.send_message(chat_id, "⚙️ *НАСТРОЙКИ*", self.create_settings_keyboard(is_admin))
            elif text == '📊 Статистика бота':
                cursor = self.conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                self.send_message(chat_id, f"📊 *Статистика*\n\nПользователей: {cursor.fetchone()[0]}")
            elif text == '👤 Мой профиль': self.send_message(chat_id, f"👤 *Ваш ID:* `{user_id}`")
            elif text == '❤️ Поддержать автора':
                self.send_message(chat_id, "❤️ *ПОДДЕРЖКА АВТОРА*\n\n💳 *Карта:* `2200 7014 1439 4772` \n👤 *Автор:* @M1PTAHKOB\n\nСпасибо! 🙏")
            elif text == '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "↩️ Главное меню", self.create_main_keyboard())
            elif text == '📢 Рассылка всем' and is_admin:
                self.waiting_for_broadcast = True
                self.send_message(chat_id, "📝 *Введите текст сообщения для рассылки:*", self.create_back_keyboard())
            elif is_admin and self.waiting_for_broadcast:
                self.waiting_for_broadcast = False
                s, f = self.broadcast_message(text)
                self.send_message(chat_id, f"✅ *Готово!*\nУспешно: {s}\nОшибок: {f}", self.create_main_keyboard())
            elif not is_admin:
                admin_msg = f"📩 *Новое сообщение!*\nОт: {message['from'].get('first_name')} (@{username})\nID: `{user_id}`\n\n💬 Текст: {text}\n\n👉 Ответить: `/send {user_id} Ваш_текст`"
                self.send_message(ADMIN, admin_msg)
                self.send_message(chat_id, "✅ Сообщение отправлено администратору.")

        except Exception as e:
            logger.error(f"Ошибка: {e}")

    def handle_today(self, chat_id):
        date = datetime.now()
        self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
        if not self.send_pdf(chat_id, self.get_pdf_url(date)): 
            self.send_message(chat_id, "❌ Расписание еще не опубликовано.")

    def handle_tomorrow(self, chat_id):
        date = datetime.now() + timedelta(days=1)
        self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
        if not self.send_pdf(chat_id, self.get_pdf_url(date)): 
            self.send_message(chat_id, "❌ Расписание еще не опубликовано.")

    def handle_check_updates(self, chat_id):
        self.send_message(chat_id, "🔍 Проверяю сайт...")
        changes = self.check_for_updates()
        if changes:
            for c in changes: self.send_pdf(chat_id, c['url'])
        else: self.send_message(chat_id, "✅ У вас актуальное расписание.")

    def broadcast_message(self, text):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        s, f = 0, 0
        for (u_id,) in cursor.fetchall():
            if self.send_message(u_id, text): s += 1
            else: f += 1
            time.sleep(0.1)
        return s, f

    def check_for_updates(self):
        changes = []
        for i in range(MAX_DAYS_BACK + 1):
            date = datetime.now() + timedelta(days=i)
            url = self.get_pdf_url(date)
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    h = hashlib.md5(r.content).hexdigest()
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT file_hash FROM file_history WHERE date = ? ORDER BY id DESC LIMIT 1", (date.strftime("%Y-%m-%d"),))
                    row = cursor.fetchone()
                    if not row or row[0] != h:
                        cursor.execute("INSERT INTO file_history (date, file_url, file_hash, file_size) VALUES (?,?,?,?)",
                                       (date.strftime("%Y-%m-%d"), url, h, len(r.content)))
                        self.conn.commit()
                        changes.append({'url': url})
            except: pass
        return changes

    def notify_all(self, changes):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
        for (u_id,) in cursor.fetchall():
            self.send_message(u_id, "🔔 *Вышло новое расписание!*")
            for c in changes: self.send_pdf(u_id, c['url'])

    def background_checker(self):
        while self.running:
            try:
                changes = self.check_for_updates()
                if changes: self.notify_all(changes)
                time.sleep(CHECK_INTERVAL)
            except: time.sleep(60)

    def run(self):
        threading.Thread(target=self.background_checker, daemon=True).start()
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'timeout': 30, 'offset': self.last_update_id + 1}, timeout=35)
                if r.status_code == 200:
                    for u in r.json().get('result', []):
                        self.last_update_id = u['update_id']
                        if 'message' in u: self.process_message(u['message'])
                time.sleep(0.2)
            except: time.sleep(5)

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
    
