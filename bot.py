#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ
Версия: 2.3 (Максимальная защита от смены названий файлов)
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
MAX_DAYS_BACK = 7    # Искать расписание на 7 дней вперед

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

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
        logger.info("🤖 Бот запущен. Система адаптивного поиска включена.")
    
    def init_db(self):
        os.makedirs("data", exist_ok=True)
        self.conn = sqlite3.connect("data/urgt_buttons.db", check_same_thread=False)
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, notifications INTEGER DEFAULT 1, last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS file_history (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, file_url TEXT, file_hash TEXT, first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        self.conn.commit()

    def get_pdf_urls(self, target_date):
        """Генерирует все возможные вариации ссылок, если админ изменит название"""
        date_str = target_date.strftime("%d%m%Y")
        # Список шаблонов, которые чаще всего использует колледж
        templates = [
            f"izmenenie-raspisanie-zanyatij-na-{date_str}-goda.pdf",
            f"izmeneniya-raspisanie-zanyatij-na-{date_str}-goda.pdf",
            f"izmenenie-raspisanie-na-{date_str}.pdf",
            f"raspisanie-na-{date_str}.pdf",
            f"raspisanie-{date_str}.pdf"
        ]
        return [f"https://urgt66.ru/media/sub/3656/files/{t}" for t in templates]

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
            response = requests.get(pdf_url, headers=HEADERS, timeout=20)
            if response.status_code == 200:
                filename = pdf_url.split('/')[-1]
                files = {'document': (filename, response.content)}
                requests.post(self.base_url + "sendDocument", 
                             data={'chat_id': chat_id, 'caption': f'📄 Найдено по ссылке:\n{filename}'}, 
                             files=files, timeout=30)
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка отправки PDF: {e}")
            return False

    def _fetch_any(self, chat_id, date, day_text):
        """Пробует все варианты ссылок для конкретной даты"""
        urls = self.get_pdf_urls(date)
        for url in urls:
            logger.info(f"Проверка: {url}")
            if self.send_pdf(chat_id, url):
                return True
        self.send_message(chat_id, f"❌ Расписание {day_text} ({date.strftime('%d.%m')}) пока не найдено.")
        return False

    def check_for_updates(self):
        """Автоматический поиск новых файлов на будущие дни"""
        found_count = 0
        for i in range(MAX_DAYS_BACK + 1):
            date = datetime.now(TZ_EKATERINBURG) + timedelta(days=i)
            for url in self.get_pdf_urls(date):
                try:
                    # Сначала проверяем HEAD запросом (быстро)
                    r = requests.head(url, headers=HEADERS, timeout=5)
                    if r.status_code == 200:
                        # Если файл есть, проверяем его хеш, чтобы не слать дубликаты
                        r_full = requests.get(url, headers=HEADERS, timeout=10)
                        h = hashlib.md5(r_full.content[:2048]).hexdigest()
                        
                        cursor = self.conn.cursor()
                        cursor.execute("SELECT id FROM file_history WHERE date=? AND file_hash=?", (date.strftime("%Y-%m-%d"), h))
                        if not cursor.fetchone():
                            cursor.execute("INSERT INTO file_history (date, file_url, file_hash) VALUES (?,?,?)", (date.strftime("%Y-%m-%d"), url, h))
                            self.conn.commit()
                            logger.info(f"🔔 Найдено новое расписание на {date.strftime('%d.%m')}!")
                            self.broadcast_new(url, date.strftime("%d.%m"))
                            found_count += 1
                            break # Нашли один вариант для этой даты — переходим к следующему дню
                except: continue
        return found_count > 0

    def broadcast_new(self, url, d_str):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
        for (u_id,) in cursor.fetchall():
            self.send_message(u_id, f"🔔 *Обнаружено новое расписание на {d_str}!*")
            self.send_pdf(u_id, url)

    def process_message(self, message):
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        text = message.get('text', '').strip()
        is_admin = str(user_id) == str(ADMIN)

        cursor = self.conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user_id, message['from'].get('first_name')))
        cursor.execute("UPDATE users SET username = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (message['from'].get('username'), user_id))
        self.conn.commit()

        if is_admin and text == '/users':
            cursor.execute("SELECT user_id, username, first_name FROM users")
            report = "👥 *Список пользователей:*\n\n"
            for u in cursor.fetchall():
                report += f"`{u[0]}` | @{u[1] if u[1] else 'нет'} | {u[2]}\n"
            self.send_message(chat_id, report[:4000])
            return

        if text in ['/start', '⬅️ Назад']:
            self.send_message(chat_id, "👋 Выберите действие:", self.create_main_keyboard())
        
        elif text == '📅 Сегодня':
            self._fetch_any(chat_id, datetime.now(TZ_EKATERINBURG), "на сегодня")
        
        elif text == '📆 Завтра':
            self._fetch_any(chat_id, datetime.now(TZ_EKATERINBURG) + timedelta(days=1), "на завтра")

        elif text == '🔍 Проверить обновления':
            self.send_message(chat_id, "🔎 Проверяю сайт УрЖТ на наличие новых файлов...")
            if not self.check_for_updates(): 
                self.send_message(chat_id, "✅ Новых файлов на ближайшую неделю не обнаружено.")

        elif text == '⚙️ Настройки':
            self.send_message(chat_id, "⚙️ Настройки", self.create_settings_keyboard(is_admin))

        elif text == '📊 Статистика бота' and is_admin:
            cursor.execute("SELECT COUNT(*) FROM users")
            u_count = cursor.fetchone()[0]
            self.send_message(chat_id, f"📊 *СТАТИСТИКА*\n👤 Пользователей: `{u_count}`")

        elif text == '🔔 Вкл/Выкл уведомления':
            cursor.execute("UPDATE users SET notifications = 1 - notifications WHERE user_id = ?", (user_id,))
            self.conn.commit()
            self.send_message(chat_id, "🔔 Статус уведомлений изменен!")

        elif text == '🔔 Расписание звонков':
            msg = "🔔 *Расписание звонков*\n\nБудни:\n1 пара: 09:00 - 10:35\n2 пара: 10:45 - 12:20\n3 пара: 13:00 - 14:35"
            self.send_message(chat_id, msg)

    def create_main_keyboard(self):
        return json.dumps({"keyboard": [[{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}], [{"text": "🔔 Расписание звонков"}], [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}]], "resize_keyboard": True})

    def create_settings_keyboard(self, is_admin):
        btns = [[{"text": "🔔 Вкл/Выкл уведомления"}]]
        if is_admin: btns.append([{"text": "📊 Статистика бота"}])
        btns.append([{"text": "⬅️ Назад"}])
        return json.dumps({"keyboard": btns, "resize_keyboard": True})

    def run(self):
        # Фоновый поток для авто-проверки обновлений
        threading.Thread(target=self.background_checker, daemon=True).start()
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'offset': self.last_update_id + 1, 'timeout': 30}).json()
                for u in r.get('result', []):
                    self.last_update_id = u['update_id']
                    if 'message' in u: self.process_message(u['message'])
            except: time.sleep(5)

    def background_checker(self):
        while self.running:
            try:
                self.check_for_updates()
                time.sleep(CHECK_INTERVAL)
            except: time.sleep(60)

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
    
