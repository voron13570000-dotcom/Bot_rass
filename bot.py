#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ С КНОПОЧНЫМ МЕНЮ И РАССЫЛКОЙ
Добавлены функции: /send ID текст и /users
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
ADMIN = "M1pTAHKOB"

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
        logger.info("👑 Админ-команды: /send ID текст, /users")
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

    # ========== ОТПРАВКА ==========
    def send_message(self, chat_id, text, keyboard=None, parse_mode='Markdown'):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode, 'disable_web_page_preview': True}
        if keyboard: params['reply_markup'] = keyboard
        
        try:
            response = requests.post(url, params=params, timeout=15)
            if response.status_code != 200:
                # Если Markdown ломается, отправляем как обычный текст
                if "can't parse entities" in response.text:
                    params.pop('parse_mode')
                    response = requests.post(url, params=params, timeout=15)
                logger.error(f"⚠️ Ошибка отправки {chat_id}: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка запроса: {e}")
            return False

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
        except Exception as e:
            logger.error(f"Ошибка PDF: {e}")
            return False

    def get_pdf_url(self, target_date):
        date_str = target_date.strftime("%d%m%Y")
        return f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date_str}.pdf"

    # ========== КЛАВИАТУРЫ ==========
    def create_main_keyboard(self):
        return json.dumps({
            "keyboard": [
                [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
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

    # ========== ОБРАБОТЧИКИ ==========
    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username', '')
            text = message.get('text', '').strip()
            is_admin = str(user_id) == ADMIN or username == ADMIN.lstrip('@')

            # КОМАНДА /users (ТОЛЬКО ДЛЯ АДМИНА)
            if is_admin and text == '/users':
                cursor = self.conn.cursor()
                cursor.execute("SELECT user_id, username, first_name FROM users")
                users_list = cursor.fetchall()
                if not users_list:
                    self.send_message(chat_id, "📭 База данных пуста.")
                else:
                    report = "👥 *Список пользователей бота:*\n\n"
                    for u in users_list:
                        report += f"ID: `{u[0]}` | @{u[1] if u[1] else 'None'} | {u[2]}\n"
                    # Если список слишком длинный, Telegram может его не принять, поэтому ограничим
                    self.send_message(chat_id, report[:4000]) 
                return

            # КОМАНДА /send ID Текст (ТОЛЬКО ДЛЯ АДМИНА)
            if is_admin and text.startswith('/send'):
                parts = text.split(maxsplit=2)
                if len(parts) == 3:
                    target_id, msg_text = parts[1], parts[2]
                    out_msg = f"✉️ *Личное сообщение от администратора:*\n\n{msg_text}"
                    if self.send_message(target_id, out_msg):
                        self.send_message(chat_id, f"✅ Доставлено пользователю `{target_id}`")
                    else:
                        self.send_message(chat_id, "❌ Не удалось отправить (неверный ID или блок).")
                else:
                    self.send_message(chat_id, "ℹ️ Формат: `/send ID Текст`")
                return

            if is_admin and self.waiting_for_broadcast and text != '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "🚀 *Запуск рассылки...*")
                success, failed = self.broadcast_message(text)
                self.send_message(chat_id, f"✅ *Готово!*\nУспешно: {success}\nОшибок: {failed}", self.create_main_keyboard())
                return

            if text in ['/start', '/старт']:
                cursor = self.conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                               (user_id, username, message['from'].get('first_name'), message['from'].get('last_name')))
                self.conn.commit()
                self.send_message(chat_id, "👋 *Бот УрЖТ готов к работе!*", self.create_main_keyboard())
            elif text == '📅 Сегодня':
                self.handle_today(chat_id)
            elif text == '📆 Завтра':
                self.handle_tomorrow(chat_id)
            elif text == '🔍 Проверить обновления':
                self.handle_check_updates(chat_id)
            elif text == '⚙️ Настройки':
                self.send_message(chat_id, "⚙️ *НАСТРОЙКИ*", self.create_settings_keyboard(is_admin))
            elif text == '📢 Рассылка всем' and is_admin:
                self.waiting_for_broadcast = True
                self.send_message(chat_id, "📝 *Введите текст сообщения для рассылки:*", self.create_back_keyboard())
            elif text == '🔔 Вкл/Выкл уведомления':
                cursor = self.conn.cursor()
                cursor.execute("SELECT notifications FROM users WHERE user_id = ?", (user_id,))
                res = cursor.fetchone()
                new_val = 0 if res and res[0] == 1 else 1
                cursor.execute("UPDATE users SET notifications = ? WHERE user_id = ?", (new_val, user_id))
                self.conn.commit()
                self.send_message(chat_id, f"🔔 Уведомления *{'ВКЛЮЧЕНЫ' if new_val == 1 else 'ВЫКЛЮЧЕНЫ'}*")
            elif text == '📊 Статистика бота':
                cursor = self.conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                self.send_message(chat_id, f"📊 Пользователей в базе: {cursor.fetchone()[0]}")
            elif text == '👤 Мой профиль':
                self.send_message(chat_id, f"👤 *Ваш ID:* `{user_id}`")
            elif text == 'ℹ️ Помощь':
                self.send_message(chat_id, "ℹ️ Бот присылает расписание УрЖТ.\nАвтоматическая проверка каждые 5 минут.")
            elif text == '❤️ Поддержать автора':
                support_text = (
                    "❤️ *ПОДДЕРЖКА АВТОРА*\n\n"
                    "Если вам нравится этот бот и вы хотите поддержать его развитие, вы можете сделать перевод по реквизитам ниже:\n\n"
                    "💳 *Карта:* `2200 7014 1439 4772`\n"
                    "👤 *Автор:* @M1PTAHKOB\n\n"
                    "Спасибо за вашу поддержку! 🙏"
                )
                self.send_message(chat_id, support_text)
            elif text == '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "↩️ Главное меню", self.create_main_keyboard())

        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")

    def handle_today(self, chat_id):
        date = datetime.now()
        self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
        if not self.send_pdf(chat_id, self.get_pdf_url(date)):
            self.send_message(chat_id, "❌ Пока не опубликовано.")

    def handle_tomorrow(self, chat_id):
        date = datetime.now() + timedelta(days=1)
        self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
        if not self.send_pdf(chat_id, self.get_pdf_url(date)):
            self.send_message(chat_id, "📭 На завтра расписания еще нет.")

    def handle_check_updates(self, chat_id):
        self.send_message(chat_id, "🔍 Проверяю сайт...")
        changes = self.check_for_updates()
        if changes:
            self.send_message(chat_id, f"✅ Найдено новых: {len(changes)}")
            for c in changes: self.send_pdf(chat_id, c['url'])
        else:
            self.send_message(chat_id, "✅ У вас актуальное расписание.")

    def broadcast_message(self, text):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        success, failed = 0, 0
        for (u_id,) in users:
            if self.send_message(u_id, text): success += 1
            else: failed += 1
            time.sleep(0.3)
        return success, failed

    def check_for_updates(self):
        changes = []
        for i in range(MAX_DAYS_BACK + 1):
            date = datetime.now() + timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            url = self.get_pdf_url(date)
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    h = hashlib.md5(r.content).hexdigest()
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT file_hash FROM file_history WHERE date = ? ORDER BY id DESC LIMIT 1", (date_str,))
                    row = cursor.fetchone()
                    if not row or row[0] != h:
                        cursor.execute("INSERT INTO file_history (date, file_url, file_hash, file_size) VALUES (?,?,?,?)",
                                       (date_str, url, h, len(r.content)))
                        self.conn.commit()
                        changes.append({'date': date_str, 'url': url})
            except: pass
        return changes

    def notify_all(self, changes):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE notifications = 1")
        users = cursor.fetchall()
        for (u_id,) in users:
            self.send_message(u_id, "🔔 *Вышло новое расписание!*")
            for c in changes: 
                self.send_pdf(u_id, c['url'])
                time.sleep(0.2)

    def console_listener(self):
        while self.running:
            try:
                cmd = input().strip()
                if cmd.startswith("send:"):
                    parts = cmd.split(":", 2)
                    if len(parts) == 3:
                        u_id, u_text = parts[1], parts[2]
                        self.send_message(u_id, u_text)
            except: pass

    def background_checker(self):
        while self.running:
            try:
                changes = self.check_for_updates()
                if changes: self.notify_all(changes)
                time.sleep(CHECK_INTERVAL)
            except: time.sleep(60)

    def run(self):
        threading.Thread(target=self.background_checker, daemon=True).start()
        threading.Thread(target=self.console_listener, daemon=True).start()
        while self.running:
            try:
                r = requests.get(self.base_url + "getUpdates", params={'timeout': 30, 'offset': self.last_update_id + 1}, timeout=35)
                if r.status_code == 200:
                    for u in r.json().get('result', []):
                        self.last_update_id = u['update_id']
                        if 'message' in u: self.process_message(u['message'])
                time.sleep(0.2)
            except KeyboardInterrupt: self.running = False
            except: time.sleep(5)

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
        
