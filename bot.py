#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ С КНОПОЧНЫМ МЕНЮ И РАССЫЛКОЙ
Настроен часовой пояс Екатеринбурга (UTC+5)
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
        logger.info(f"🕒 Часовой пояс: UTC+5 (Екатеринбург)")
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
            response = requests.get(pdf_url, timeout=20)
            if response.status_code == 200:
                # ИСПРАВЛЕНИЕ: Передаем имя файла, чтобы Telegram видел PDF
                filename = pdf_url.split('/')[-1]
                files = {'document': (filename, response.content)}
                
                requests.post(self.base_url + "sendDocument", 
                             data={'chat_id': chat_id, 'caption': '📄 Расписание УрЖТ'}, 
                             files=files, timeout=30)
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка отправки PDF: {e}")
            return False

    def get_pdf_url(self, target_date):
        date_str = target_date.strftime("%d%m%Y")
        return f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date_str}.pdf"

    def create_main_keyboard(self):
        return json.dumps({
            "keyboard": [
                [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
                [{"text": "🔔 Расписание звонков"}],
                [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}],
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
        now = datetime.now(TZ_EKATERINBURG)
        day_of_week = now.weekday() 
        header = "🔔 *ЗВОНКИ УрЖТ (Екатеринбург)*\n"

        if day_of_week == 0:
            bells_text = (
                f"{header}📍 *Тип дня:* Понедельник\n\n"
                "📢 `08:30 — 08:40` Линейка\n"
                "🏫 `08:45 — 09:30` Классный час\n"
                "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
                "1️⃣ `09:40 — 11:15` 1-я пара\n"
                "2️⃣ `11:25 — 13:00` 2-я пара\n"
                "🍱 `13:00 — 13:40` *ОБЕД*\n"
                "3️⃣ `13:40 — 15:15` 3-я пара\n"
                "4️⃣ `15:35 — 17:10` 4-я пара\n"
                "5️⃣ `17:20 — 18:55` 5-я пара\n"
                "6️⃣ `19:05 — 20:40` 6-я пара"
            )
        elif day_of_week == 5:
            bells_text = (
                f"{header}📍 *Тип дня:* Суббота\n\n"
                "1️⃣ `09:00 — 10:35` 1-я пара\n"
                "2️⃣ `10:45 — 12:20` 2-я пара\n"
                "🍱 `12:20 — 12:40` *ОБЕД*\n"
                "3️⃣ `12:40 — 14:15` 3-я пара\n"
                "4️⃣ `14:25 — 16:00` 4-я пара"
            )
        else:
            bells_text = (
                f"{header}📍 *Тип дня:* Будни\n\n"
                "1️⃣ `09:00 — 10:35` 1-я пара\n"
                "2️⃣ `10:45 — 12:20` 2-я пара\n"
                "🍱 `12:20 — 13:00` *ОБЕД*\n"
                "3️⃣ `13:00 — 14:30` 3-я пара\n"
                "4️⃣ `14:50 — 16:25` 4-я пара\n"
                "5️⃣ `16:35 — 18:10` 5-я пара\n"
                "6️⃣ `18:20 — 19:55` 6-я пара"
            )
        self.send_message(chat_id, bells_text)

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username', '')
            first_name = message['from'].get('first_name', 'User')
            text = message.get('text', '').strip()
            is_admin = str(user_id) == str(ADMIN)

            cursor = self.conn.cursor()
            cursor.execute("SELECT notifications FROM users WHERE user_id = ?", (user_id,))
            user_data = cursor.fetchone()
            
            if not user_data:
                cursor.execute("INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                               (user_id, username, first_name))
                self.conn.commit()
                safe_username = username.replace('_', '\\_') if username else "нет"
                self.send_message(ADMIN, f"🆕 *Новый пользователь:* {first_name} (@{safe_username})\nID: `{user_id}`")
                current_notifications = 1
            else:
                current_notifications = user_data[0]
                cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
                self.conn.commit()

            if is_admin and text == '/users':
                cursor.execute("SELECT user_id, username, first_name FROM users")
                users_list = cursor.fetchall()
                report = "👥 *Список пользователей:*\n\n"
                for u in users_list:
                    u_name = f"@{u[1]}".replace('_', '\\_') if u[1] else "нет"
                    report += f"`{u[0]}` | {u_name} | {u[2]}\n"
                self.send_message(chat_id, report[:4000])
                return

            if is_admin and text.startswith('/send'):
                parts = text.split(maxsplit=2)
                if len(parts) == 3:
                    self.send_message(parts[1], f"✉️ *Личное сообщение от администратора:*\n\n{parts[2]}")
                return

            if text in ['/start', '/старт']:
                self.send_message(chat_id, "👋 *Бот УрЖТ готов к работе!*", self.create_main_keyboard())
            
            elif text == '🔔 Вкл/Выкл уведомления':
                new_status = 0 if current_notifications == 1 else 1
                cursor.execute("UPDATE users SET notifications = ? WHERE user_id = ?", (new_status, user_id))
                self.conn.commit()
                status_text = "ВКЛЮЧЕНЫ ✅" if new_status == 1 else "ВЫКЛЮЧЕНЫ ❌"
                self.send_message(chat_id, f"🔔 Уведомления теперь *{status_text}*")

            elif text == '📅 Сегодня': self.handle_today(chat_id)
            elif text == '📆 Завтра': self.handle_tomorrow(chat_id)
            elif text == '🔔 Расписание звонков': self.handle_bells(chat_id)
            elif text == '🔍 Проверить обновления': self.handle_check_updates(chat_id)
            elif text == '⚙️ Настройки': self.send_message(chat_id, "⚙️ *НАСТРОЙКИ*", self.create_settings_keyboard(is_admin))
            elif text == '📊 Статистика бота':
                cursor.execute("SELECT COUNT(*) FROM users")
                self.send_message(chat_id, f"📊 *Статистика*\n\nПользователей: {cursor.fetchone()[0]}")
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
                admin_msg = f"📩 *Новое сообщение!*\nОт: {first_name} (@{username})\nID: `{user_id}`\n\n💬 Текст: {text}\n\n👉 Ответить: `/send {user_id} Ваш_текст`"
                self.send_message(ADMIN, admin_msg)
                self.send_message(chat_id, "✅ Сообщение отправлено администратору.")

        except Exception as e:
            logger.error(f"Ошибка: {e}")

    def handle_today(self, chat_id):
        date = datetime.now(TZ_EKATERINBURG)
        if not self.send_pdf(chat_id, self.get_pdf_url(date)): 
            self.send_message(chat_id, "❌ Расписание на сегодня еще не опубликовано.")

    def handle_tomorrow(self, chat_id):
        date = datetime.now(TZ_EKATERINBURG) + timedelta(days=1)
        if not self.send_pdf(chat_id, self.get_pdf_url(date)): 
            self.send_message(chat_id, "❌ Расписание на завтра еще не опубликовано.")

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
            date = datetime.now(TZ_EKATERINBURG) + timedelta(days=i)
            url = self.get_pdf_url(date)
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    h = hashlib.md5(r.content).hexdigest()
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT id FROM file_history WHERE date = ? AND file_hash = ?", (date.strftime("%Y-%m-%d"), h))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO file_history (date, file_url, file_hash, file_size) VALUES (?,?,?,?)",
                                       (date.strftime("%Y-%m-%d"), url, h, len(r.content)))
                        self.conn.commit()
                        changes.append({'url': url, 'date': date.strftime('%d.%m')})
            except: pass
        return changes

    def background_checker(self):
        while self.running:
            try:
                changes = self.check_for_updates()
                if changes:
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
                    users = cursor.fetchall()
                    for (u_id,) in users:
                        for c in changes:
                            self.send_message(u_id, f"🔔 *Обнаружено новое расписание на {c['date']}!*")
                            self.send_pdf(u_id, c['url'])
                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Ошибка фонового монитора: {e}")
                time.sleep(60)

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
    
