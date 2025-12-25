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

log_handler = RotatingFileHandler('urgt_bot.log', maxBytes=2*1024*1024, backupCount=1, encoding='utf-8')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[log_handler, logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

class Button_URGT_Bot:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/"
        self.init_db()
        self.last_update_id = 0
        self.running = True
        self.waiting_for_broadcast = False
        logger.info("🤖 БОТ ЗАПУЩЕН (ЗВОНКИ УДАЛЕНЫ, ФОРМАТ /USERS ОБНОВЛЕН)")
    
    def init_db(self):
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
        cursor.execute("CREATE TABLE IF NOT EXISTS file_history (id INTEGER PRIMARY KEY AUTOINCREMENT, file_url TEXT, file_hash TEXT UNIQUE)")
        self.conn.commit()

    def send_message(self, chat_id, text, keyboard=None):
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
        if keyboard: params['reply_markup'] = keyboard
        return requests.post(self.base_url + "sendMessage", params=params)

    def send_pdf(self, chat_id, pdf_url):
        try:
            r = requests.get(pdf_url, timeout=25)
            if r.status_code == 200:
                filename = pdf_url.split('/')[-1]
                files = {'document': (filename, r.content)}
                requests.post(self.base_url + "sendDocument", data={'chat_id': chat_id}, files=files)
                return True
        except: return False

    def get_links_from_site(self):
        links = []
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            r = requests.get(SITE_URL, headers=headers, timeout=20)
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                if '.pdf' in a['href'].lower():
                    href = a['href'] if a['href'].startswith('http') else "https://urgt66.ru" + a['href']
                    links.append(href)
        except: pass
        return list(set(links))

    def create_main_keyboard(self):
        # Кнопка звонков полностью удалена отсюда
        return json.dumps({"keyboard": [
            [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
            [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}],
            [{"text": "❤️ Поддержать автора"}]
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
        # Обновляем данные пользователя при каждом сообщении (на случай смены ника)
        cursor.execute("INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
                       (user_id, message['from'].get('username'), message['from'].get('first_name')))
        self.conn.commit()

        if text == '/start':
            self.send_message(chat_id, "👋 Бот расписания УрЖТ готов к работе.", self.create_main_keyboard())

        elif text == '📅 Сегодня' or text == '📆 Завтра':
            self.send_message(chat_id, "🔎 Ищу файл...")
            days = 0 if 'Сегодня' in text else 1
            date_str = (datetime.now(TZ_EKATERINBURG) + timedelta(days=days)).strftime("%d%m%Y")
            links = self.get_links_from_site()
            found = any(self.send_pdf(chat_id, l) for l in links if date_str in l)
            if not found: self.send_message(chat_id, "❌ Расписание на этот день еще не опубликовано.")

        elif text == '🔍 Проверить обновления':
            self.send_message(chat_id, "🔎 Проверка...")
            links = self.get_links_from_site()
            new = 0
            for l in links:
                r = requests.get(l); h = hashlib.md5(r.content).hexdigest()
                cursor.execute("SELECT id FROM file_history WHERE file_hash=?", (h,))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO file_history (file_url, file_hash) VALUES (?, ?)", (l, h))
                    self.conn.commit(); self.send_pdf(chat_id, l); new += 1
            if new == 0: self.send_message(chat_id, "✅ Новых файлов нет.")

        elif text == '⚙️ Настройки':
            self.send_message(chat_id, "⚙️ Настройки:", self.create_settings_keyboard(is_admin))

        elif text == '🔔 Вкл/Выкл уведомления':
            cursor.execute("UPDATE users SET notifications = 1 - notifications WHERE user_id = ?", (user_id,))
            self.conn.commit()
            self.send_message(chat_id, "✅ Статус уведомлений изменен.")

        elif text == '👥 Список пользователей' or text == '/users':
            if is_admin:
                cursor.execute("SELECT user_id, first_name, username FROM users")
                users = cursor.fetchall()
                res = "👥 *Список пользователей:*\n"
                for u in users:
                    username = f"(@{u[2]})" if u[2] else "(нет юзернейма)"
                    res += f"• `{u[0]}`: {u[1]} {username}\n"
                self.send_message(chat_id, res)

        elif text == '📢 Рассылка всем' and is_admin:
            self.waiting_for_broadcast = True
            self.send_message(chat_id, "📝 Введите текст для всех пользователей:")

        elif is_admin and self.waiting_for_broadcast and text != '⬅️ Назад':
            self.waiting_for_broadcast = False
            cursor.execute("SELECT user_id FROM users")
            for (u_id,) in cursor.fetchall():
                self.send_message(u_id, f"📢 *ОБЪЯВЛЕНИЕ:*\n{text}")
            self.send_message(chat_id, "✅ Готово.", self.create_main_keyboard())

        elif text.startswith('/send ') and is_admin:
            try:
                parts = text.split(maxsplit=2)
                target_id = parts[1]
                msg_body = parts[2]
                # Добавляем блок обратной связи
                footer = "\n\n---\n💬 *Вы можете ответить на это сообщение, просто написав боту.*"
                self.send_message(target_id, f"✉️ *Сообщение от администратора:*\n{msg_body}{footer}")
                self.send_message(chat_id, f"✅ Отправлено пользователю `{target_id}`")
            except: self.send_message(chat_id, "❌ Ошибка. Формат: `/send ID Текст`")

        elif not is_admin and text and not text.startswith('/'):
            # Если обычный пользователь пишет текст, пересылаем админу для "обратной связи"
            username = f"@{message['from'].get('username')}" if message['from'].get('username') else "без ника"
            self.send_message(ADMIN, f"📩 *Новое сообщение от {message['from'].get('first_name')}* (`{user_id}`, {username}):\n\n{text}")
            self.send_message(chat_id, "✅ Ваше сообщение отправлено администратору.")

        elif text == '⬅️ Назад' or text == '❤️ Поддержать автора':
            if 'Поддержать' in text: self.send_message(chat_id, "💳 Карта: `2200 7014 1439 4772`")
            else: self.send_message(chat_id, "↩️ Меню", self.create_main_keyboard())

    def run(self):
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'offset': self.last_update_id + 1, 'timeout': 20})
                if r.status_code == 200:
                    for u in r.json().get('result', []):
                        self.last_update_id = u['update_id']
                        if 'message' in u: self.process_message(u['message'])
            except: time.sleep(5)

if __name__ == "__main__":
    Button_URGT_Bot().run()
        
