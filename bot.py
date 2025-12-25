#!/usr/bin/env python3
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
from logging.handlers import RotatingFileHandler
from bs4 import BeautifulSoup

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8534692585:AAHRp6JsPORhX3KF-bqM2bPQz0RuWEKVxt8" 
ADMIN = "7634746932" 
TZ_EKATERINBURG = timezone(timedelta(hours=5)) 

CHECK_INTERVAL = 300
SITE_URL = "https://urgt66.ru/partition/136056/"

# ЗАЩИТА ОТ ПЕРЕПОЛНЕНИЯ ДИСКА (макс 2 МБ)
log_handler = RotatingFileHandler('urgt_bot.log', maxBytes=2*1024*1024, backupCount=1, encoding='utf-8')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[log_handler, logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class Button_URGT_Bot:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/"
        self.init_db()
        self.last_update_id = 0
        self.running = True
        self.waiting_for_broadcast = False
        logger.info("🤖 БОТ ЗАПУЩЕН С ПОЛНЫМ ФУНКЦИОНАЛОМ")
    
    def init_db(self):
        try:
            os.makedirs("data", exist_ok=True)
            self.conn = sqlite3.connect("data/urgt_buttons.db", check_same_thread=False)
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    notifications INTEGER DEFAULT 1,
                    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_url TEXT,
                    file_hash TEXT UNIQUE,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка БД: {e}")

    def send_message(self, chat_id, text, keyboard=None):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
        if keyboard: params['reply_markup'] = keyboard
        try:
            return requests.post(url, params=params, timeout=15)
        except: return None

    def send_pdf(self, chat_id, pdf_url):
        try:
            r = requests.get(pdf_url, timeout=25)
            if r.status_code == 200:
                filename = pdf_url.split('/')[-1]
                files = {'document': (filename, r.content)}
                requests.post(self.base_url + "sendDocument", data={'chat_id': chat_id}, files=files, timeout=35)
                return True
            return False
        except: return False

    def get_links_from_site(self):
        links = []
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        try:
            r = requests.get(SITE_URL, headers=headers, timeout=30)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if '.pdf' in href.lower():
                        if not href.startswith('http'): href = "https://urgt66.ru" + href
                        links.append(href)
        except Exception as e: logger.error(f"Парсинг: {e}")
        return list(set(links))

    def check_and_save_file(self, url):
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                h = hashlib.md5(r.content).hexdigest()
                cursor = self.conn.cursor()
                cursor.execute("SELECT id FROM file_history WHERE file_hash = ?", (h,))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO file_history (file_url, file_hash) VALUES (?, ?)", (url, h))
                    self.conn.commit()
                    return True
        except: pass
        return False

    def create_main_keyboard(self):
        return json.dumps({"keyboard": [
            [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
            [{"text": "🔔 Расписание звонков"}, {"text": "❤️ Поддержать автора"}],
            [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}]
        ], "resize_keyboard": True})

    def create_settings_keyboard(self, is_admin):
        btns = [[{"text": "🔔 Вкл/Выкл уведомления"}]]
        if is_admin: btns.append([{"text": "👥 Список пользователей"}, {"text": "📢 Рассылка всем"}])
        btns.append([{"text": "⬅️ Назад"}])
        return json.dumps({"keyboard": btns, "resize_keyboard": True})

    def process_message(self, message):
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        text = message.get('text', '').strip()
        is_admin = str(user_id) == str(ADMIN)

        cursor = self.conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                       (user_id, message['from'].get('username'), message['from'].get('first_name')))
        self.conn.commit()

        if text == '/start':
            self.send_message(chat_id, "👋 Привет! Я бот расписания УрЖТ.", self.create_main_keyboard())

        elif text == '📅 Сегодня':
            self.send_message(chat_id, "🔍 Проверяю сайт...")
            date_str = datetime.now(TZ_EKATERINBURG).strftime("%d%m%Y")
            links = self.get_links_from_site()
            found = any(self.send_pdf(chat_id, l) for l in links if date_str in l)
            if not found: self.send_message(chat_id, "❌ Файл не найден.")

        elif text == '📆 Завтра':
            self.send_message(chat_id, "🔍 Проверяю сайт...")
            date_str = (datetime.now(TZ_EKATERINBURG) + timedelta(days=1)).strftime("%d%m%Y")
            links = self.get_links_from_site()
            found = any(self.send_pdf(chat_id, l) for l in links if date_str in l)
            if not found: self.send_message(chat_id, "❌ Файл не найден.")

        elif text == '🔔 Расписание звонков':
            self.send_message(chat_id, "🔔 *РАСПИСАНИЕ ЗВОНКОВ*\n1. 09:00-10:35\n2. 10:45-12:20\n3. 13:00-14:35")

        elif text == '❤️ Поддержать автора':
            self.send_message(chat_id, "❤️ Поддержать автора: @M1PTAHKOB\nКарта: `2200 7014 1439 4772`")

        elif text == '🔍 Проверить обновления':
            self.send_message(chat_id, "🔎 Ищу новые файлы...")
            links = self.get_links_from_site()
            new = sum(1 for l in links if self.check_and_save_file(l) and self.send_pdf(chat_id, l))
            if new == 0: self.send_message(chat_id, "✅ Новых файлов нет.")

        elif text == '⚙️ Настройки':
            self.send_message(chat_id, "⚙️ Настройки бота:", self.create_settings_keyboard(is_admin))

        elif text == '🔔 Вкл/Выкл уведомления':
            cursor.execute("UPDATE users SET notifications = 1 - notifications WHERE user_id = ?", (user_id,))
            self.conn.commit()
            cursor.execute("SELECT notifications FROM users WHERE user_id = ?", (user_id,))
            status = "ВКЛ" if cursor.fetchone()[0] == 1 else "ВЫКЛ"
            self.send_message(chat_id, f"✅ Уведомления: {status}")

        elif text == '👥 Список пользователей' or text == '/users':
            if is_admin:
                cursor.execute("SELECT user_id, first_name FROM users")
                users = cursor.fetchall()
                self.send_message(chat_id, "👥 *Юзеры:*\n" + "\n".join([f"`{u[0]}` - {u[1]}" for u in users]))

        elif text == '📢 Рассылка всем' and is_admin:
            self.waiting_for_broadcast = True
            self.send_message(chat_id, "📝 Введите текст для рассылки или нажмите Назад.", json.dumps({"keyboard": [[{"text": "⬅️ Назад"}]], "resize_keyboard": True}))

        elif is_admin and self.waiting_for_broadcast and text != '⬅️ Назад':
            self.waiting_for_broadcast = False
            cursor.execute("SELECT user_id FROM users")
            for (u_id,) in cursor.fetchall(): self.send_message(u_id, f"📢 *ОБЪЯВЛЕНИЕ:*\n{text}")
            self.send_message(chat_id, "✅ Рассылка завершена!", self.create_main_keyboard())

        elif text == '⬅️ Назад':
            self.waiting_for_broadcast = False
            self.send_message(chat_id, "↩️ Главное меню", self.create_main_keyboard())

        elif text.startswith('/send ') and is_admin:
            parts = text.split(maxsplit=2)
            if len(parts) == 3: self.send_message(parts[1], f"✉️ *Личное сообщение:* {parts[2]}")

    def background_checker(self):
        while self.running:
            try:
                links = self.get_links_from_site()
                for l in links:
                    if self.check_and_save_file(l):
                        cursor = self.conn.cursor()
                        cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
                        for (u_id,) in cursor.fetchall():
                            self.send_message(u_id, "🔔 Новое расписание на сайте!")
                            self.send_pdf(u_id, l)
                time.sleep(CHECK_INTERVAL)
            except: time.sleep(60)

    def run(self):
        threading.Thread(target=self.background_checker, daemon=True).start()
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'offset': self.last_update_id + 1, 'timeout': 30})
                if r.status_code == 200:
                    for u in r.json().get('result', []):
                        self.last_update_id = u['update_id']
                        if 'message' in u: self.process_message(u['message'])
            except: time.sleep(5)

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
    
