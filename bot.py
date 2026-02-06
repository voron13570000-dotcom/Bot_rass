#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ
Версия: 2.1 (Полный функционал: Изменения + Админ-панель)
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
    format='%(asctime)s - %(levelname)s - %(message)s',
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
        
        logger.info("🤖 БОТ УрЖТ ЗАПУЩЕН")
    
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
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                file_url TEXT,
                file_hash TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def get_pdf_urls(self, target_date):
        """Формирует список вариантов ссылок (с изменениями и без)"""
        date_str = target_date.strftime("%d%m%Y")
        return [
            # Формат с изменениями (новый)
            f"https://urgt66.ru/media/sub/3656/files/izmeneniya-raspisanie-zanyatij-na-{date_str}-goda.pdf",
            # Стандартный формат
            f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date_str}.pdf"
        ]

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
            response = requests.get(pdf_url, timeout=20)
            if response.status_code == 200:
                filename = pdf_url.split('/')[-1]
                files = {'document': (filename, response.content)}
                requests.post(self.base_url + "sendDocument", 
                             data={'chat_id': chat_id, 'caption': f'📄 Найдено: {filename}'}, 
                             files=files, timeout=30)
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

    def create_settings_keyboard(self, is_admin=False):
        buttons = [[{"text": "🔔 Вкл/Выкл уведомления"}]]
        if is_admin: 
            buttons.append([{"text": "📊 Статистика бота"}])
            buttons.append([{"text": "📢 Рассылка всем"}])
        buttons.append([{"text": "⬅️ Назад"}])
        return json.dumps({"keyboard": buttons, "resize_keyboard": True})

    def process_message(self, message):
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        text = message.get('text', '').strip()
        is_admin = str(user_id) == str(ADMIN)

        # Обновление данных пользователя
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user_id, message['from'].get('first_name')))
        cursor.execute("UPDATE users SET username = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?", 
                       (message['from'].get('username'), user_id))
        self.conn.commit()

        # Команда вывода пользователей (только админ)
        if is_admin and text == '/users':
            cursor.execute("SELECT user_id, username, first_name FROM users")
            users_list = cursor.fetchall()
            report = "👥 *Список пользователей:*\n\n"
            for u in users_list:
                u_name = f"@{u[1]}".replace('_', '\\_') if u[1] else "нет"
                report += f"`{u[0]}` | {u_name} | {u[2]}\n"
            self.send_message(chat_id, report[:4000])
            return

        if text in ['/start', '⬅️ Назад']:
            self.waiting_for_broadcast = False
            self.send_message(chat_id, "👋 Главное меню", self.create_main_keyboard())
        
        elif text == '📅 Сегодня':
            self._fetch_any(chat_id, datetime.now(TZ_EKATERINBURG), "на сегодня")
        
        elif text == '📆 Завтра':
            self._fetch_any(chat_id, datetime.now(TZ_EKATERINBURG) + timedelta(days=1), "на завтра")

        elif text == '🔍 Проверить обновления':
            self.send_message(chat_id, "🔎 Проверяю сайт УрЖТ...")
            if not self.check_for_updates(): self.send_message(chat_id, "✅ У вас актуальное расписание.")

        elif text == '⚙️ Настройки':
            self.send_message(chat_id, "⚙️ Настройки бота", self.create_settings_keyboard(is_admin))

        elif text == '📊 Статистика бота' and is_admin:
            cursor.execute("SELECT COUNT(*) FROM users")
            u_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM file_history")
            f_count = cursor.fetchone()[0]
            self.send_message(chat_id, f"📊 *СТАТИСТИКА*\n\n👤 Пользователей: `{u_count}`\n📄 Файлов в базе: `{f_count}`")

        elif text == '🔔 Вкл/Выкл уведомления':
            cursor.execute("UPDATE users SET notifications = 1 - notifications WHERE user_id = ?", (user_id,))
            self.conn.commit()
            cursor.execute("SELECT notifications FROM users WHERE user_id = ?", (user_id,))
            status = "ВКЛЮЧЕНЫ ✅" if cursor.fetchone()[0] == 1 else "ВЫКЛЮЧЕНЫ ❌"
            self.send_message(chat_id, f"🔔 Уведомления теперь *{status}*")

        elif text == '🔔 Расписание звонков':
            self.handle_bells(chat_id)

        elif text == '❤️ Поддержать автора':
            self.send_message(chat_id, "💳 Карта: `2200 7014 1439 4772` \nАвтор: @M1PTAHKOB")

        elif text == '📢 Рассылка всем' and is_admin:
            self.waiting_for_broadcast = True
            self.send_message(chat_id, "📝 Введите текст для рассылки всем:", json.dumps({"keyboard": [[{"text": "⬅️ Назад"}]], "resize_keyboard": True}))

        elif self.waiting_for_broadcast and is_admin:
            self.waiting_for_broadcast = False
            cursor.execute("SELECT user_id FROM users")
            s, f = 0, 0
            for (u_id,) in cursor.fetchall():
                if self.send_message(u_id, f"📢 *ОБЪЯВЛЕНИЕ*\n\n{text}"): s += 1
                else: f += 1
            self.send_message(chat_id, f"✅ Готово!\nУспешно: {s}\nОшибок: {f}", self.create_main_keyboard())

    def handle_bells(self, chat_id):
        day = datetime.now(TZ_EKATERINBURG).weekday()
        if day == 0:
            msg = "🔔 *Понедельник*\nЛинейка: 08:30\n1 пара: 09:40-11:15\n2 пара: 11:25-13:00\n3 пара: 13:40-15:15"
        elif day == 5:
            msg = "🔔 *Суббота*\n1 пара: 09:00-10:35\n2 пара: 10:45-12:20\n3 пара: 12:40-14:15"
        else:
            msg = "🔔 *Будни*\n1 пара: 09:00-10:35\n2 пара: 10:45-12:20\n3 пара: 13:00-14:35\n4 пара: 14:50-16:25"
        self.send_message(chat_id, msg)

    def _fetch_any(self, chat_id, date, day_text):
        for url in self.get_pdf_urls(date):
            if self.send_pdf(chat_id, url): return
        self.send_message(chat_id, f"❌ Расписание {day_text} не найдено.")

    def check_for_updates(self):
        found = False
        for i in range(MAX_DAYS_BACK + 1):
            date = datetime.now(TZ_EKATERINBURG) + timedelta(days=i)
            for url in self.get_pdf_urls(date):
                try:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        h = hashlib.md5(r.content[:1024]).hexdigest()
                        cursor = self.conn.cursor()
                        cursor.execute("SELECT id FROM file_history WHERE date=? AND file_hash=?", (date.strftime("%Y-%m-%d"), h))
                        if not cursor.fetchone():
                            cursor.execute("INSERT INTO file_history (date, file_url, file_hash) VALUES (?,?,?)", (date.strftime("%Y-%m-%d"), url, h))
                            self.conn.commit()
                            self.broadcast_new(url, date.strftime("%d.%m"))
                            found = True
                            break # Если нашли один вариант для даты, второй не нужен
                except: continue
        return found

    def broadcast_new(self, url, d_str):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
        for (u_id,) in cursor.fetchall():
            self.send_message(u_id, f"🔔 *Новое расписание на {d_str}!*")
            self.send_pdf(u_id, url)

    def background_checker(self):
        while self.running:
            try:
                self.check_for_updates()
                time.sleep(CHECK_INTERVAL)
            except: time.sleep(60)

    def run(self):
        threading.Thread(target=self.background_checker, daemon=True).start()
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'offset': self.last_update_id + 1, 'timeout': 30}).json()
                for u in r.get('result', []):
                    self.last_update_id = u['update_id']
                    if 'message' in u: self.process_message(u['message'])
            except: time.sleep(5)

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
    
