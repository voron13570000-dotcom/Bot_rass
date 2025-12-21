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

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8534692585:AAHRp6JsPORhX3KF-bqM2bPQz0RuWEKVxt8" 
ADMIN_ID = 7634746932  # ВАШ ID для гарантированного доступа
ADMIN_USERNAME = "M1pTAHKOB"

CHECK_INTERVAL = 300 
MAX_DAYS_BACK = 7    

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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
        
        logger.info("🤖 БОТ ЗАПУЩЕН")
    
    def init_db(self):
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
        buttons.append([{"text": "📊 Статистика бота"}, {"text": "⬅️ Назад"}])
        return json.dumps({"keyboard": buttons, "resize_keyboard": True})

    def send_message(self, chat_id, text, keyboard=None, parse_mode='Markdown'):
        url = self.base_url + "sendMessage"
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        if keyboard: params['reply_markup'] = keyboard
        try:
            r = requests.post(url, params=params, timeout=10)
            return r.status_code == 200
        except: return False

    # ========== ОБРАБОТЧИКИ ==========

    def process_message(self, message):
        try:
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username', '')
            text = message.get('text', '').strip()
            
            # Проверка прав админа по ID или Username
            is_admin = (user_id == ADMIN_ID or username == ADMIN_USERNAME)

            if is_admin and self.waiting_for_broadcast and text != '⬅️ Назад':
                self.waiting_for_broadcast = False
                self.send_message(chat_id, "🚀 Рассылка запущена...")
                s, f = self.broadcast_message(text)
                self.send_message(chat_id, f"✅ Успешно: {s}, Ошибок: {f}", self.create_main_keyboard())
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
                self.send_message(chat_id, "⚙️ Настройки:", self.create_settings_keyboard(is_admin))
            elif text == '👥 Список пользователей' and is_admin:
                self.handle_user_list(chat_id)
            elif text == '📢 Рассылка всем' and is_admin:
                self.waiting_for_broadcast = True
                self.send_message(chat_id, "📝 Введите текст сообщения:", json.dumps({"keyboard": [[{"text": "⬅️ Назад"}]], "resize_keyboard": True}))
            elif text == '📊 Статистика бота':
                self.handle_statistics(chat_id)
            elif text == '⬅️ Назад':
                self.send_message(chat_id, "🏠 Главное меню", self.create_main_keyboard())
            # ... другие команды ...
            
        except Exception as e:
            logger.error(f"Ошибка: {e}")

    def handle_start(self, chat_id, user_info):
        uid = user_info['id']
        uname = user_info.get('username', '')
        fname = user_info.get('first_name', 'User')
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,))
        is_new = cursor.fetchone() is None
        
        cursor.execute("INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (uid, uname, fname))
        self.conn.commit()
        
        self.send_message(chat_id, "👋 Привет! Я бот расписания УрЖТ.", self.create_main_keyboard())
        
        if is_new and uid != ADMIN_ID:
            msg = f"🆕 *Новый пользователь!*\n👤 {fname}\n🔗 @{uname}\n🆔 `{uid}`"
            self.send_message(ADMIN_ID, msg)

    def handle_user_list(self, chat_id):
        """Исправленный метод получения списка"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT user_id, username, first_name FROM users ORDER BY created DESC")
            users = cursor.fetchall()
            
            if not users:
                self.send_message(chat_id, "📭 Список пуст.")
                return

            # Формируем сообщение
            header = f"👥 *Список пользователей (всего: {len(users)}):*\n\n"
            lines = []
            for u_id, username, first_name in users:
                user_tag = f"@{username}" if username else f"[{first_name}](tg://user?id={u_id})"
                lines.append(f"• {user_tag} (`{u_id}`)")
            
            # Отправляем частями, если список длинный (лимит TG 4096 символов)
            full_text = header + "\n".join(lines)
            if len(full_text) > 4000:
                for x in range(0, len(lines), 50):
                    part = "\n".join(lines[x:x+50])
                    self.send_message(chat_id, part)
            else:
                self.send_message(chat_id, full_text)
                
        except Exception as e:
            logger.error(f"Ошибка БД в списке: {e}")
            self.send_message(chat_id, "❌ Ошибка при получении списка из базы данных.")

    def handle_statistics(self, chat_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        self.send_message(chat_id, f"📊 *Статистика*\nВсего пользователей: {total}")

    # ... функции проверки обновлений и рассылки остаются без изменений ...
    
    def broadcast_message(self, text):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        s, f = 0, 0
        for (u_id,) in users:
            if self.send_message(u_id, text): s += 1
            else: f += 1
        return s, f

    def run(self):
        # Запуск фонового потока проверки (код из вашего файла)
        # ...
        logger.info("📡 Бот в сети...")
        while self.running:
            try:
                updates = self.get_updates()
                for u in updates:
                    self.last_update_id = u['update_id']
                    if 'message' in u: self.process_message(u['message'])
                time.sleep(0.3)
            except: time.sleep(5)

    def get_updates(self, timeout=30):
        url = self.base_url + "getUpdates"
        params = {'timeout': timeout, 'offset': self.last_update_id + 1}
        try:
            r = requests.get(url, params=params, timeout=timeout+5)
            return r.json().get('result', [])
        except: return []

if __name__ == "__main__":
    bot = Button_URGT_Bot()
    bot.run()
