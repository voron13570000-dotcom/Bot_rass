#!/usr/bin/env python3
"""
БОТ ДЛЯ РАСПИСАНИЯ УрЖТ С КНОПОЧНЫМ МЕНЮ И РАССЫЛКОЙ
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
import traceback
import shutil

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8534692585:AAHRp6JsPORhX3KF-bqM2bPQz0RuWEKVxt8" 
ADMIN_USERNAME = "M1pTAHKOB"  # Ваш username без @

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
            logger.info("✅ База данных инициализирована")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            raise

    # ========== КЛАВИАТУРЫ ==========
    
    def create_main_keyboard(self):
        keyboard = {
            "keyboard": [
                [{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
                [{"text": "🔍 Проверить обновления"}, {"text": "⚙️ Настройки"}],
                [{"text": "ℹ️ Помощь"}, {"text": "👤 Мой профиль"}],
                [{"text": "❤️ Поддержать автора"}]
            ],
            "resize_keyboard": True
        }
        return json.dumps(keyboard)
    
    def create_settings_keyboard(self, is_admin=False):
        buttons = [[{"text": "🔔 Вкл/Выкл уведомления"}]]
        if is_admin:
            buttons.append([{"text": "📢 Рассылка всем"}, {"text": "👥 Список пользователей"}])
        buttons.append([{"text": "📊 Статистика бота"}])
        buttons.append([{"text": "⬅️ Назад"}])
        
        keyboard = {"keyboard": buttons, "resize_keyboard": True}
        return json.dumps(keyboard)
    
    def create_back_keyboard(self):
        keyboard = {"keyboard": [[{"text": "⬅️ Назад"}]], "resize_keyboard": True}
        return json.dumps(keyboard)

    # ========== ОТПРАВКА ==========

    def send_message(self, chat_id, text, keyboard=None, parse_mode='Markdown'):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode, 'disable_web_page_preview': True}
        if keyboard: params['reply_markup'] = keyboard
        
        try:
            response = requests.post(url, params=params, timeout=15)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            return False

    def send_pdf(self, chat_id, pdf_url):
        try:
            os.makedirs("temp", exist_ok=True)
            response = requests.get(pdf_url, timeout=20, stream=True)
            if response.status_code == 200:
                temp_file = "temp/temp_schedule.pdf"
                with open(temp_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                url = self.base_url + "sendDocument"
                with open(temp_file, "rb") as file:
                    files = {'document': file}
                    data = {'chat_id': chat_id, 'caption': '📄 Расписание УрЖТ'}
                    requests.post(url, data=data, files=files, timeout=30)
                if os.path.exists(temp_file): os.remove(temp_file)
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка PDF: {e}")
            return False

    def get_pdf_url(self, target_date):
        date_str = target_date.strftime("%d%m%Y")
        return f"https://urgt66.ru/media/sub/3656/files/raspisanie-na-{date_str}.pdf"

    # ========== ОБРАБОТЧИКИ ==========

    def handle_settings(self, chat_id, user_id, username):
        is_admin = username == ADMIN_USERNAME
        msg = "⚙️ *НАСТРОЙКИ БОТА*\n\nВыберите нужное действие ниже:"
        if is_admin: msg += "\n\n👑 *Меню администратора активно*"
        self.send_message(chat_id, msg, self.create_settings_keyboard(is_admin))

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username', '')
            text = message.get('text', '').strip()
            is_admin = username == ADMIN_USERNAME

            if is_admin and self.waiting_for_broadcast and text != '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "🚀 *Запуск рассылки...*")
                success, failed = self.broadcast_message(text)
                self.send_message(chat_id, f"✅ *Готово!*\nУспешно: {success}\nОшибок: {failed}", self.create_main_keyboard())
                return

            if text in ['/start', '/старт']:
                self.handle_start(chat_id, message['from'])
            elif text == '📅 Сегодня':
                self.handle_today(chat_id)
            elif text == '📆 Завтра':
                self.handle_tomorrow(chat_id)
            elif text == '🔍 Проверить обновления':
                self.handle_check_updates(chat_id)
            elif text == '⚙️ Настройки':
                self.handle_settings(chat_id, user_id, username)
            elif text == '📢 Рассылка всем' and is_admin:
                self.waiting_for_broadcast = True
                self.send_message(chat_id, "📝 *Введите текст сообщения для рассылки:*", self.create_back_keyboard())
            elif text == '👥 Список пользователей' and is_admin:
                self.handle_user_list(chat_id)
            elif text == '🔔 Вкл/Выкл уведомления':
                self.handle_toggle_notifications(chat_id, user_id)
            elif text == '📊 Статистика бота':
                self.handle_statistics(chat_id)
            elif text == '👤 Мой профиль':
                self.handle_profile(chat_id, user_id)
            elif text == 'ℹ️ Помощь':
                self.handle_help(chat_id)
            elif text == '❤️ Поддержать автора':
                self.handle_support(chat_id)
            elif text == '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "↩️ Главное меню", self.create_main_keyboard())
            else:
                self.send_message(chat_id, "🤖 Используйте кнопки меню.", self.create_main_keyboard())

        except Exception as e:
            logger.error(f"Ошибка процесса: {e}")

    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========

    def handle_start(self, chat_id, user_info):
        """Регистрация пользователя и уведомление админа о новом юзере"""
        user_id = user_info['id']
        username = user_info.get('username', '')
        first_name = user_info.get('first_name', 'Без имени')
        
        cursor = self.conn.cursor()
        # Проверяем, есть ли пользователь в базе
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        is_new = cursor.fetchone() is None
        
        # Сохраняем/обновляем данные
        cursor.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_active) 
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, username, first_name, user_info.get('last_name')))
        self.conn.commit()
        
        self.send_message(chat_id, "👋 *Бот УрЖТ готов к работе!*", self.create_main_keyboard())

        # Если пользователь новый — уведомляем админа
        if is_new:
            self.notify_admin_about_new_user(user_info)

    def notify_admin_about_new_user(self, user_info):
        """Поиск ID админа и отправка ему уведомления с обновленным списком"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE username = ?", (ADMIN_USERNAME,))
        admin_data = cursor.fetchone()
        
        if admin_data:
            admin_id = admin_data[0]
            name = user_info.get('first_name', 'User')
            uname = f"@{user_info.get('username')}" if user_info.get('username') else "нет"
            
            msg = f"🆕 *Новый пользователь!*\n👤 Имя: {name}\n🔗 Юзернейм: {uname}\n🆔 ID: `{user_info['id']}`"
            self.send_message(admin_id, msg)
            
            # Сразу присылаем админу обновленный список
            self.handle_user_list(admin_id)

    def handle_user_list(self, chat_id):
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT user_id, username, first_name FROM users ORDER BY created DESC LIMIT 50")
            users = cursor.fetchall()
            
            if not users:
                self.send_message(chat_id, "📭 Список пользователей пуст.")
                return

            response = "👥 *Последние пользователи (всего: " + str(len(users)) + "):*\n\n"
            for u_id, username, first_name in users:
                user_info = f"@{username}" if username else f"[{first_name}](tg://user?id={u_id})"
                response += f"• {user_info} (ID: `{u_id}`)\n"
            
            self.send_message(chat_id, response)
        except Exception as e:
            logger.error(f"Ошибка списка: {e}")

    def handle_support(self, chat_id):
        support_text = (
            "❤️ *ПОДДЕРЖКА АВТОРА*\n\n"
            "Карта: `2200 7014 1439 4772`\n"
            "Автор: @M1PTAHKOB"
        )
        self.send_message(chat_id, support_text)

    def handle_today(self, chat_id):
        date = datetime.now()
        url = self.get_pdf_url(date)
        self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
        if not self.send_pdf(chat_id, url):
            self.send_message(chat_id, "❌ Расписание еще не опубликовано.")

    def handle_tomorrow(self, chat_id):
        date = datetime.now() + timedelta(days=1)
        url = self.get_pdf_url(date)
        self.send_message(chat_id, f"🔍 Ищу на {date.strftime('%d.%m.%Y')}...")
        if not self.send_pdf(chat_id, url):
            self.send_message(chat_id, "📭 На завтра расписания пока нет.")

    def handle_statistics(self, chat_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        self.send_message(chat_id, f"📊 *Статистика*\n\nВсего пользователей: {count}")

    def handle_toggle_notifications(self, chat_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT notifications FROM users WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        if res:
            new_val = 0 if res[0] == 1 else 1
            cursor.execute("UPDATE users SET notifications = ? WHERE user_id = ?", (new_val, user_id))
            self.conn.commit()
            status = "ВКЛЮЧЕНЫ" if new_val == 1 else "ВЫКЛЮЧЕНЫ"
            self.send_message(chat_id, f"🔔 Уведомления {status}")

    def handle_profile(self, chat_id, user_id):
        self.send_message(chat_id, f"👤 *Ваш ID:* `{user_id}`")

    def handle_help(self, chat_id):
        self.send_message(chat_id, "ℹ️ Бот присылает расписание УрЖТ.\nОбновления проверяются автоматически.")

    def handle_check_updates(self, chat_id):
        self.send_message(chat_id, "🔍 Проверяю сайт...")
        changes = self.check_for_updates()
        if changes:
            self.send_message(chat_id, f"✅ Найдено новых файлов: {len(changes)}")
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
            time.sleep(0.05)
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
            for c in changes: self.send_pdf(u_id, c['url'])

    def background_checker(self):
        while self.running:
            try:
                changes = self.check_for_updates()
                if changes: self.notify_all(changes)
                time.sleep(CHECK_INTERVAL)
            except: time.sleep(60)

    def get_updates(self, timeout=30):
        url = self.base_url + "getUpdates"
        params = {'timeout': timeout, 'offset': self.last_update_id + 1}
        try:
            r = requests.get(url, params=params, timeout=timeout+5)
            if r.status_code == 200:
                data = r.json()
                return data.get('result', [])
        except: return []
        return []

    def run(self):
        threading.Thread(target=self.background_checker, daemon=True).start()
        logger.info("📡 Бот запущен...")
        while self.running:
            try:
                updates = self.get_updates()
                for u in updates:
                    self.last_update_id = u['update_id']
                    if 'message' in u: self.process_message(u['message'])
                time.sleep(0.2)
            except KeyboardInterrupt: self.running = False
            except: time.sleep(5)

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
