#!/usr/bin/env python3
"""
ФИНАЛЬНАЯ ВЕРСИЯ: БОТ УрЖТ 2025-2026
Мониторинг, Авто-регистрация, Умные звонки (UTC+5)
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
CHECK_INTERVAL = 300 # Проверка сайта каждые 5 минут

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('urgt_bot.log', encoding='utf-8')]
)
logger = logging.getLogger(__name__)

class Full_URGT_Bot:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/"
        self.init_db()
        self.last_update_id = 0
        self.running = True
        self.waiting_for_broadcast = False
        
        logger.info("=" * 60)
        logger.info("🤖 БОТ УрЖТ ЗАПУЩЕН (ПОЛНАЯ ФУНКЦИОНАЛЬНОСТЬ)")
        logger.info("=" * 60)
    
    def init_db(self):
        os.makedirs("data", exist_ok=True)
        self.conn = sqlite3.connect("data/urgt_buttons.db", check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                notifications INTEGER DEFAULT 1
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                file_hash TEXT
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

    def send_pdf(self, chat_id, pdf_url, caption='📄 Расписание УрЖТ'):
        try:
            r = requests.get(pdf_url, timeout=20)
            if r.status_code == 200:
                requests.post(self.base_url + "sendDocument", 
                             data={'chat_id': chat_id, 'caption': caption}, 
                             files={'document': r.content}, timeout=30)
                return True
            return False
        except: return False

    # --- ЛОГИКА МОНИТОРИНГА САЙТА ---
    def check_site_for_new_files(self):
        updates = []
        # Проверяем на сегодня и на 3 дня вперед
        for i in range(4):
            date = datetime.now(TZ_EKATERINBURG) + timedelta(days=i)
            date_str = date.strftime("%d%m%Y")
            url = f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date_str}.pdf"
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    h = hashlib.md5(r.content).hexdigest()
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT id FROM file_history WHERE date=? AND file_hash=?", (date_str, h))
                    if not cursor.fetchone():
                        cursor.execute("INSERT INTO file_history (date, file_hash) VALUES (?,?)", (date_str, h))
                        self.conn.commit()
                        updates.append((url, date.strftime("%d.%m.%Y")))
            except: pass
        return updates

    def background_checker(self):
        """Функция работает в отдельном потоке и проверяет сайт"""
        while self.running:
            try:
                new_files = self.check_site_for_new_files()
                if new_files:
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
                    users = cursor.fetchall()
                    for url, d_text in new_files:
                        for (u_id,) in users:
                            self.send_message(u_id, f"🔔 *Обнаружено новое расписание на {d_text}!*")
                            self.send_pdf(u_id, url)
                            time.sleep(0.05) # Плавная рассылка
                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Ошибка фона: {e}")
                time.sleep(60)

    # --- ГЛАВНОЕ МЕНЮ ---
    def create_main_keyboard(self):
        return json.dumps({
            "keyboard": [
                [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
                [{"text": "🔔 Расписание звонков"}],
                [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}],
                [{"text": "❤️ Поддержать автора"}]
            ], "resize_keyboard": True
        })

    def handle_bells(self, chat_id):
        now = datetime.now(TZ_EKATERINBURG)
        day = now.weekday()
        if day == 0: # ПОНЕДЕЛЬНИК
            msg = "🔔 *ЗВОНКИ (Понедельник)*\n📢 Линейка: 08:30\n🏫 КЧ: 08:45 — 09:30\n1 пара: 09:40 — 11:15\n2 пара: 11:25 — 13:00\n🍱 Обед: 13:00\n3 пара: 13:40 — 15:15"
        elif day == 5: # СУББОТА
            msg = "🔔 *ЗВОНКИ (Суббота)*\n1 пара: 09:00 — 10:35\n2 пара: 10:45 — 12:20\n🍱 Обед: 12:20\n3 пара: 12:40 — 14:15"
        else: # БУДНИ
            msg = "🔔 *ЗВОНКИ (Вторник-Пятница)*\n1 пара: 09:00 — 10:35\n2 пара: 10:45 — 12:20\n🍱 Обед: 12:20\n3 пара: 13:00 — 14:30"
        self.send_message(chat_id, msg)

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username', 'NoName')
            text = message.get('text', '').strip()
            is_admin = str(user_id) == str(ADMIN)

            # --- АВТО-РЕГИСТРАЦИЯ ПРИ ЛЮБОМ ДЕЙСТВИИ ---
            cursor = self.conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                           (user_id, username, message['from'].get('first_name')))
            self.conn.commit()

            if text in ['/start', '/старт']:
                self.send_message(chat_id, "👋 *Бот УрЖТ активен!* Я автоматически пришлю расписание, как только оно выйдет на сайте.", self.create_main_keyboard())
            
            elif text == '📅 Сегодня':
                d = datetime.now(TZ_EKATERINBURG)
                url = f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{d.strftime('%d%m%Y')}.pdf"
                if not self.send_pdf(chat_id, url, f"📅 На сегодня ({d.strftime('%d.%m')})"):
                    self.send_message(chat_id, "❌ На сегодня расписания еще нет.")

            elif text == '📆 Завтра':
                d = datetime.now(TZ_EKATERINBURG) + timedelta(days=1)
                url = f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{d.strftime('%d%m%Y')}.pdf"
                if not self.send_pdf(chat_id, url, f"📆 На завтра ({d.strftime('%d.%m')})"):
                    self.send_message(chat_id, "❌ На завтра расписания еще нет.")

            elif text == '🔔 Расписание звонков':
                self.handle_bells(chat_id)

            elif text == '🔍 Проверить обновления':
                self.send_message(chat_id, "🔎 Проверяю сайт УрЖТ...")
                new = self.check_site_for_new_files()
                if not new: self.send_message(chat_id, "✅ У вас самое актуальное расписание.")
                for url, dt in new: self.send_pdf(chat_id, url, f"📄 Найдено новое: {dt}")

            elif text == '⚙️ Настройки':
                kb = json.dumps({"keyboard": [[{"text": "🔔 Вкл/Выкл уведомления"}], [{"text": "⬅️ Назад"}]], "resize_keyboard": True})
                self.send_message(chat_id, "⚙️ *НАСТРОЙКИ*", kb)

            elif text == '📢 Рассылка всем' and is_admin:
                self.waiting_for_broadcast = True
                self.send_message(chat_id, "📝 Введите текст рассылки:", json.dumps({"keyboard": [[{"text": "⬅️ Назад"}]], "resize_keyboard": True}))

            elif is_admin and self.waiting_for_broadcast:
                self.waiting_for_broadcast = False
                cursor.execute("SELECT user_id FROM users")
                users = cursor.fetchall()
                s, f = 0, 0
                for (u_id,) in users:
                    if self.send_message(u_id, f"📢 *ОБЪЯВЛЕНИЕ:*\n\n{text}"): s += 1
                    else: f += 1
                self.send_message(chat_id, f"✅ Рассылка окончена.\nУспешно: {s}, Ошибок: {f}", self.create_main_keyboard())

            elif text == '❤️ Поддержать автора':
                self.send_message(chat_id, "❤️ *ПОДДЕРЖКА*\n💳 Карта: `2200 7014 1439 4772` \nАвтор: @M1PTAHKOB")

            elif text == '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "↩️ Главное меню", self.create_main_keyboard())

            elif not is_admin and text:
                self.send_message(ADMIN, f"📩 *Сообщение от {username}* (ID: `{user_id}`):\n{text}")
                self.send_message(chat_id, "✅ Сообщение отправлено админу.")

        except Exception as e:
            logger.error(f"Ошибка: {e}")

    def run(self):
        # Запуск фоновой проверки в отдельном потоке
        threading.Thread(target=self.background_checker, daemon=True).start()
        # Основной цикл получения сообщений
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'timeout': 30, 'offset': self.last_update_id + 1})
                if r.status_code == 200:
                    for u in r.json().get('result', []):
                        self.last_update_id = u['update_id']
                        if 'message' in u: self.process_message(u['message'])
                time.sleep(0.2)
            except: time.sleep(5)

if __name__ == "__main__":
    Full_URGT_Bot().run()
