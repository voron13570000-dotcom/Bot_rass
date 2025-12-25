#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ (УМНАЯ ВЕРСИЯ)
- Исправлена ссылка на новый раздел расписания (136056)
- Добавлен парсинг BeautifulSoup
- Защита диска от переполнения (Rotating Logs)
- Корректная отправка PDF имен
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
from logging.handlers import RotatingFileHandler
from bs4 import BeautifulSoup

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8534692585:AAHRp6JsPORhX3KF-bqM2bPQz0RuWEKVxt8" 
ADMIN = "7634746932" 
TZ_EKATERINBURG = timezone(timedelta(hours=5)) 

CHECK_INTERVAL = 300
MAX_DAYS_BACK = 7
# НОВЫЙ URL РАЗДЕЛА РАСПИСАНИЯ
SITE_URL = "https://urgt66.ru/partition/136056/"

# Настройка логов с авто-очисткой (макс 2 МБ)
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
        
        logger.info("=" * 60)
        logger.info("🤖 УМНЫЙ БОТ УрЖТ ЗАПУЩЕН")
        logger.info(f"📍 Мониторинг раздела: {SITE_URL}")
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
                    file_url TEXT,
                    file_hash TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(file_hash)
                )
            """)
            self.conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка БД: {e}")

    def send_message(self, chat_id, text, keyboard=None, parse_mode='Markdown'):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode, 'disable_web_page_preview': True}
        if keyboard: params['reply_markup'] = keyboard
        try:
            response = requests.post(url, params=params, timeout=15)
            return response.status_code == 200
        except: return False

    def send_pdf(self, chat_id, pdf_url):
        try:
            response = requests.get(pdf_url, timeout=25)
            if response.status_code == 200:
                filename = pdf_url.split('/')[-1]
                if not filename.lower().endswith('.pdf'):
                    filename += ".pdf"
                
                files = {'document': (filename, response.content)}
                requests.post(self.base_url + "sendDocument", 
                             data={'chat_id': chat_id, 'caption': '📄 Расписание УрЖТ'}, 
                             files=files, timeout=35)
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка отправки PDF: {e}")
            return False

    def get_links_from_site(self):
        """Парсинг сайта с имитацией браузера"""
        links = []
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        try:
            r = requests.get(SITE_URL, headers=headers, timeout=30)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if '.pdf' in href.lower():
                        if not href.startswith('http'):
                            href = "https://urgt66.ru" + href
                        links.append(href)
                logger.info(f"Найдено PDF на странице: {len(links)}")
            else:
                logger.error(f"Сайт вернул ошибку {r.status_code}")
        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")
        return list(set(links))

    def check_and_save_file(self, url):
        """Проверка новизны файла по его содержимому (хешу)"""
        try:
            r = requests.get(url, timeout=20)
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

    def handle_bells(self, chat_id):
        now = datetime.now(TZ_EKATERINBURG)
        day = now.weekday() 
        header = "🔔 *ЗВОНКИ УрЖТ*\n"
        if day == 0:
            msg = f"{header}📍 Понедельник\n\n📢 `08:30-08:40` Линейка\n🏫 `08:45-09:30` Кл.час\n1. `09:40-11:15`..."
        elif day == 5:
            msg = f"{header}📍 Суббота\n\n1. `09:00-10:35`\n2. `10:45-12:20`..."
        else:
            msg = f"{header}📍 Будни\n\n1. `09:00-10:35`\n2. `10:45-12:20`\n🍱 Обед `12:20-13:00`..."
        self.send_message(chat_id, msg)

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            text = message.get('text', '').strip()
            is_admin = str(user_id) == str(ADMIN)

            cursor = self.conn.cursor()
            cursor.execute("SELECT notifications FROM users WHERE user_id = ?", (user_id,))
            user_data = cursor.fetchone()
            
            if not user_data:
                cursor.execute("INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                               (user_id, message['from'].get('username'), message['from'].get('first_name')))
                self.conn.commit()
                current_notifications = 1
            else:
                current_notifications = user_data[0]

            if text in ['/start', '/старт']:
                self.send_message(chat_id, "👋 Бот УрЖТ готов!", self.create_main_keyboard())
            
            elif text == '📅 Сегодня':
                self.send_message(chat_id, "🔍 Ищу файлы на сегодня...")
                links = self.get_links_from_site()
                found = False
                today = datetime.now(TZ_EKATERINBURG).strftime("%d%m%Y")
                for link in links:
                    if today in link:
                        self.send_pdf(chat_id, link)
                        found = True
                if not found: self.send_message(chat_id, "❌ Файл на сегодня не найден на сайте.")

            elif text == '📆 Завтра':
                self.send_message(chat_id, "🔍 Ищу файлы на завтра...")
                links = self.get_links_from_site()
                found = False
                tomorrow = (datetime.now(TZ_EKATERINBURG) + timedelta(days=1)).strftime("%d%m%Y")
                for link in links:
                    if tomorrow in link:
                        self.send_pdf(chat_id, link)
                        found = True
                if not found: self.send_message(chat_id, "❌ Файл на завтра не найден.")

            elif text == '🔍 Проверить обновления':
                self.send_message(chat_id, "🔎 Сканирую раздел расписания...")
                links = self.get_links_from_site()
                new_files = 0
                for link in links:
                    if self.check_and_save_file(link):
                        self.send_pdf(chat_id, link)
                        new_files += 1
                if new_files == 0: self.send_message(chat_id, "✅ Новых файлов пока нет.")

            elif text == '⚙️ Настройки': self.send_message(chat_id, "⚙️ Настройки", self.create_settings_keyboard(is_admin))
            elif text == '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "↩️ Главное меню", self.create_main_keyboard())
            elif text == '📢 Рассылка всем' and is_admin:
                self.waiting_for_broadcast = True
                self.send_message(chat_id, "📝 Введите текст сообщения:", json.dumps({"keyboard": [[{"text": "⬅️ Назад"}]], "resize_keyboard": True}))
            elif is_admin and self.waiting_for_broadcast:
                self.waiting_for_broadcast = False
                cursor.execute("SELECT user_id FROM users")
                for (u_id,) in cursor.fetchall():
                    self.send_message(u_id, text)
                self.send_message(chat_id, "✅ Рассылка завершена.", self.create_main_keyboard())

        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")

    def background_checker(self):
        while self.running:
            try:
                links = self.get_links_from_site()
                for link in links:
                    if self.check_and_save_file(link):
                        cursor = self.conn.cursor()
                        cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
                        for (u_id,) in cursor.fetchall():
                            self.send_message(u_id, "🔔 На сайте новое расписание!")
                            self.send_pdf(u_id, link)
                            time.sleep(0.2)
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
    
