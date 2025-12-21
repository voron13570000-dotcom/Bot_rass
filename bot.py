#!/usr/bin/env python3
"""
ИСПРАВЛЕННЫЙ БОТ УрЖТ
Администратор: 7634746932
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
ADMIN_ID = 7634746932  # Ваш фиксированный ID
ADMIN_USERNAME = "M1pTAHKOB"

CHECK_INTERVAL = 300 
MAX_DAYS_BACK = 7    

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Button_URGT_Bot:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/"
        self.init_db()
        self.last_update_id = 0
        self.running = True
        self.waiting_for_broadcast = False 

    def init_db(self):
        """Инициализация базы данных"""
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

    # ========== ОТПРАВКА СООБЩЕНИЙ ==========

    def send_message(self, chat_id, text, keyboard=None):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
        if keyboard: params['reply_markup'] = keyboard
        try:
            r = requests.post(url, params=params, timeout=10)
            return r.status_code == 200
        except: return False

    def send_pdf(self, chat_id, pdf_url):
        """Скачивание и отправка PDF расписания"""
        try:
            os.makedirs("temp", exist_ok=True)
            r = requests.get(pdf_url, timeout=20, stream=True)
            if r.status_code == 200:
                temp_file = "temp/temp_schedule.pdf"
                with open(temp_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                url = self.base_url + "sendDocument"
                with open(temp_file, "rb") as file:
                    requests.post(url, data={'chat_id': chat_id, 'caption': '📄 Расписание УрЖТ'}, files={'document': file}, timeout=30)
                if os.path.exists(temp_file): os.remove(temp_file)
                return True
            return False
        except: return False

    def get_pdf_url(self, target_date):
        date_str = target_date.strftime("%d%m%Y")
        return f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date_str}.pdf"

    # ========== ОБРАБОТЧИКИ ==========

    def handle_user_list(self, chat_id):
        """Вывод списка пользователей для админа"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT user_id, username, first_name FROM users ORDER BY created DESC")
            users = cursor.fetchall()
            
            if not users:
                self.send_message(chat_id, "📭 Список пользователей пуст.")
                return

            response = f"👥 *Всего пользователей: {len(users)}*\n\n"
            for u_id, username, first_name in users:
                user_tag = f"@{username}" if username else f"{first_name}"
                line = f"• {user_tag} (ID: `{u_id}`)\n"
                
                if len(response) + len(line) > 3900:
                    self.send_message(chat_id, response)
                    response = ""
                response += line
            
            if response:
                self.send_message(chat_id, response)
        except Exception as e:
            self.send_message(chat_id, f"❌ Ошибка БД: {e}")

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            text = message.get('text', '')
            is_admin = (user_id == ADMIN_ID)

            if is_admin and self.waiting_for_broadcast and text != '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.broadcast_message(text)
                self.send_message(chat_id, "✅ Рассылка завершена.")
                return

            if text in ['/start', '⬅️ Назад']:
                self.handle_start(chat_id, message['from'])
            elif text == '📅 Сегодня':
                url = self.get_pdf_url(datetime.now())
                if not self.send_pdf(chat_id, url): self.send_message(chat_id, "❌ Нет расписания на сегодня.")
            elif text == '📆 Завтра':
                url = self.get_pdf_url(datetime.now() + timedelta(days=1))
                if not self.send_pdf(chat_id, url): self.send_message(chat_id, "📭 На завтра пока нет.")
            elif text == '🔍 Проверить обновления':
                self.send_message(chat_id, "🔎 Проверяю сайт...")
                self.check_for_updates()
            elif text == '⚙️ Настройки':
                kb = {
                    "keyboard": [
                        [{"text": "🔔 Вкл/Выкл уведомления"}],
                        [{"text": "👥 Список пользователей"}] if is_admin else [],
                        [{"text": "📊 Статистика бота"}, {"text": "⬅️ Назад"}]
                    ], "resize_keyboard": True
                }
                self.send_message(chat_id, "⚙️ Настройки:", json.dumps(kb))
            elif text == '👥 Список пользователей' and is_admin:
                self.handle_user_list(chat_id)
            elif text == '📊 Статистика бота':
                cursor = self.conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                self.send_message(chat_id, f"📈 Всего пользователей: {cursor.fetchone()[0]}")
            elif text == '📢 Рассылка всем' and is_admin:
                self.waiting_for_broadcast = True
                self.send_message(chat_id, "📝 Введите текст сообщения:", json.dumps({"keyboard":[[{"text":"⬅️ Назад"}]],"resize_keyboard":True}))

        except Exception as e:
            logger.error(f"Ошибка: {e}")

    def handle_start(self, chat_id, user_info):
        uid, uname, fname = user_info['id'], user_info.get('username', ''), user_info.get('first_name', 'User')
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,))
        is_new = cursor.fetchone() is None
        cursor.execute("INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (uid, uname, fname))
        self.conn.commit()
        
        kb = {"keyboard": [[{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}], [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}]], "resize_keyboard": True}
        self.send_message(chat_id, "🏠 Главное меню", json.dumps(kb))
        
        if is_new and uid != ADMIN_ID:
            self.send_message(ADMIN_ID, f"🆕 *Новый пользователь!*\n👤 {fname}\n🔗 @{uname}\n🆔 `{uid}`")

    # ========== АНАЛИЗ САЙТА ==========

    def check_for_updates(self):
        """Анализ обновлений на сайте"""
        changes = []
        for i in range(MAX_DAYS_BACK + 1):
            date = datetime.now() + timedelta(days=i)
            url = self.get_pdf_url(date)
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    h = hashlib.md5(r.content).hexdigest()
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT file_hash FROM file_history WHERE date = ?", (date.strftime("%Y-%m-%d"),))
                    row = cursor.fetchone()
                    if not row or row[0] != h:
                        cursor.execute("INSERT OR REPLACE INTO file_history (date, file_hash) VALUES (?, ?)", (date.strftime("%Y-%m-%d"), h))
                        self.conn.commit()
                        changes.append(url)
            except: pass
        if changes:
            self.notify_all(changes)
        return changes

    def notify_all(self, urls):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
        for (u_id,) in cursor.fetchall():
            self.send_message(u_id, "🔔 *Обновление расписания!*")
            for url in urls: self.send_pdf(u_id, url)

    def background_checker(self):
        while self.running:
            try:
                self.check_for_updates()
                time.sleep(CHECK_INTERVAL)
            except: time.sleep(60)

    def get_updates(self):
        try:
            r = requests.get(f"{self.base_url}getUpdates", params={'offset': self.last_update_id + 1, 'timeout': 20}, timeout=25)
            return r.json().get('result', [])
        except: return []

    def run(self):
        threading.Thread(target=self.background_checker, daemon=True).start()
        logger.info("📡 Бот УрЖТ запущен...")
        while self.running:
            for u in self.get_updates():
                self.last_update_id = u['update_id']
                if 'message' in u: self.process_message(u['message'])
            time.sleep(0.5)

if __name__ == "__main__":
    Button_URGT_Bot().run()
