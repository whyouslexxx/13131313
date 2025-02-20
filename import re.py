import schedule
import time
import threading
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from PIL import Image, ImageEnhance, ImageFilter
from io import BytesIO
import os
import requests
from dotenv import load_dotenv
import telebot
import random
import sqlite3
import logging

# Инициализация конфигурации
load_dotenv()
DB_NAME = 'zcoin.db'
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = 7495017933 
GROUP_IDS = [-1002287219772, -1002408503345]
SCHEDULE_URL = "https://coworking.tyuiu.ru/shs/all_t/sh.php?action=group&union=0&sid=28704&gr=844&year=2025&vr=1"
WEATHERAPI_KEY = os.getenv('WEATHERAPI_KEY')
WORK_COOLDOWN = 20 * 60  # 20 минут в секундах
MIN_REWARD = 1
MAX_REWARD = 50
MINEFIELD_SIZE = 5
MIN_REWARD_MULTIPLIER = 1.1
MAX_REWARD_MULTIPLIER = 5.0
ROB_COOLDOWN = 3600  # 1 час в секундах
MIN_ROB = 20
MAX_ROB = 300
SUCCESS_CHANCE = 40  # 40% шанс успеха
FINE_PERCENT = 20    # 20% штраф при неудаче
REQUEST_COOLDOWN = 90

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

bot = telebot.TeleBot(BOT_TOKEN)
user_messages = []
active_games = {}

def forward_to_admin(message):
    """Пересылает сообщение администратору и добавляет информацию о пользователе и содержание сообщения"""
    if message.from_user.id == ADMIN_ID:
        return  # Игнорируем сообщения от администратора
    
    try:
        # Пересылаем сообщение администратору
        bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)

        # Формируем информацию о пользователе и содержании сообщения
        user_info = (
            f"👤 Пользователь:\n"
            f"ID: {message.from_user.id}\n"
            f"Имя: {message.from_user.first_name}\n"
            f"Фамилия: {message.from_user.last_name}\n"
            f"Username: @{message.from_user.username}\n"
            f"📄 Сообщение: {message.text if message.text else 'Нет текста (фото, документ, стикер и т.д.)'}"
        )
        bot.send_message(ADMIN_ID, user_info)
    except Exception as e:
        logging.error(f"Ошибка при пересылке сообщения администратору: {str(e)}")
@bot.message_handler(commands=['расписание'])
def handle_schedule_command(message):
    """Обработчик команды /расписание"""
    handle_schedule(message)

@bot.message_handler(func=lambda message: message.chat.type == 'private', content_types=['text', 'photo', 'document', 'audio', 'voice', 'sticker'])
def handle_private_messages(message):
    """Пересылает все личные сообщения администратору и обрабатывает команды"""
    try:
        # Обработка команд
        if message.text and message.text.startswith('/'):
            if message.text.startswith('/баланс'):
                handle_balance(message)
            elif message.text.startswith('/работа'):
                handle_work(message)
            elif message.text.startswith('/минер'):
                handle_mine(message)
            elif message.text.startswith('/передать'):
                handle_transfer(message)
            elif message.text.startswith('/погода'):
                handle_weather(message)
            else:
                bot.send_message(message.chat.id, "Неизвестная команда")
            
            # Пересылаем команду администратору
            forward_to_admin(message)
        else:
            # Пересылаем не командные сообщения администратору
            forward_to_admin(message)
    except Exception as e:
        logging.error(f"Ошибка обработки личного сообщения: {str(e)}")
        bot.send_message(message.chat.id, "Произошла ошибка при обработке сообщения.")
@bot.message_handler(commands=['чек'])
def handle_create_check(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()

        if len(args) != 3:
            return bot.reply_to(message, "ℹ Используйте: /чек [сумма] [пароль]")

        try:
            amount = int(args[1])
            if amount <= 0:
                return bot.reply_to(message, "❌ Сумма должна быть больше нуля!")
        except ValueError:
            return bot.reply_to(message, "❌ Некорректная сумма! Используйте целое число.")

        password = args[2].strip()
        if not password:
            return bot.reply_to(message, "❌ Пароль не может быть пустым!")

        # Проверяем баланс пользователя
        balance = get_balance(user_id)
        if balance < amount:
            return bot.reply_to(message, f"❌ Недостаточно средств! Ваш баланс: {format_number(balance)} zcoin")

        # Создаем чек
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO checks (user_id, amount, password) VALUES (?, ?, ?)",
                  (user_id, amount, password))
        conn.commit()

        # Получаем ID созданного чека
        check_id = c.lastrowid

        # Снимаем сумму с баланса пользователя
        update_balance(user_id, -amount)

        # Отправляем пользователю информацию о чеке
        bot.reply_to(message,
                     f"✅ Чек успешно создан!\n"
                     f"🆔 ID чека: {check_id}\n"
                     f"💰 Сумма: {format_number(amount)} zcoin\n"
                     f"🔑 Пароль: {password}\n\n"
                     f"💼 Ваш новый баланс: {format_number(get_balance(user_id))} zcoin")

    except Exception as e:
        logging.error(f"Ошибка создания чека: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при создании чека")
    finally:
        conn.close()
@bot.message_handler(commands=['активировать'])
def handle_activate_check(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()

        if len(args) != 3:
            return bot.reply_to(message, "ℹ Используйте: /активировать [ID чека] [пароль]")

        try:
            check_id = int(args[1])
        except ValueError:
            return bot.reply_to(message, "❌ Некорректный ID чека! Используйте целое число.")

        password = args[2].strip()

        # Проверяем чек в базе данных
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id, amount, is_used FROM checks WHERE id = ? AND password = ?",
                  (check_id, password))
        check = c.fetchone()

        if not check:
            return bot.reply_to(message, "❌ Чек не найден или пароль неверный!")

        creator_id, amount, is_used = check

        if is_used:
            return bot.reply_to(message, "❌ Этот чек уже был использован!")

        # Активируем чек
        update_balance(user_id, amount)
        c.execute("UPDATE checks SET is_used = 1 WHERE id = ?", (check_id,))
        conn.commit()

        # Уведомляем пользователя
        bot.reply_to(message,
                    f"✅ Чек успешно активирован!\n"
                    f"💰 Получено: {format_number(amount)} zcoin\n"
                    f"💼 Ваш новый баланс: {format_number(get_balance(user_id))} zcoin")

        # Уведомляем создателя чека (если он не активирует свой же чек)
        if creator_id != user_id:
            bot.send_message(creator_id,
                            f"ℹ Ваш чек #{check_id} был активирован пользователем @{message.from_user.username}.")

    except Exception as e:
        logging.error(f"Ошибка активации чека: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при активации чека")
    finally:
        conn.close()
@bot.message_handler(commands=['топ'])
def handle_top(message):
    """Отображает таблицу лидеров по балансу"""
    try:
        # Подключение к базе данных
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        # Запрос для получения всех пользователей с их балансами, сортируем по балансу
        c.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
        leaders = c.fetchall()

        # Логирование результатов запроса
        logging.debug(f"Лидеры: {leaders}")

        # Если таблица лидеров пуста
        if not leaders:
            return bot.reply_to(message, "❌ Нет данных для отображения таблицы лидеров.")

        # Формирование строки с топ-10 пользователями
        leaderboard = "🏆 Топ 10 пользователей по балансу:\n"
        for idx, (user_id, balance) in enumerate(leaders, 1):
            try:
                user_info = bot.get_chat(user_id)
                username = user_info.username if user_info.username else "Неизвестный"
                leaderboard += f"{idx}. @{username} - {format_number(balance)} zcoin\n"
            except Exception as e:
                logging.error(f"Ошибка при получении данных пользователя {user_id}: {str(e)}")
                leaderboard += f"{idx}. Пользователь с ID {user_id} - ошибка получения данных\n"

        # Отправка таблицы лидеров пользователю
        bot.reply_to(message, leaderboard)

    except Exception as e:
        logging.error(f"Ошибка получения таблицы лидеров: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при получении таблицы лидеров.")
    finally:
        conn.close()
def get_last_robbery(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT last_robbery FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0


# Обработчик команды /ограбить
@bot.message_handler(commands=['ограбить'])
def handle_rob(message):
    try:
        user_id = message.from_user.id
        target = message.reply_to_message

        if not target:
            return bot.reply_to(message, "❌ Нужно ответить на сообщение пользователя, которого хотите ограбить!")

        target_user = target.from_user
        target_id = target_user.id

        if user_id == target_id:
            return bot.reply_to(message, "❌ Нельзя грабить самого себя!хд")

        if target_id == bot.get_me().id:
            return bot.reply_to(message, "💢 реал? ограбить бота? Ты потерял 5000 zcoin!")
            update_balance(user_id, -5000)
            return

        last_rob = get_last_robbery(user_id)
        current_time = time.time()

        if current_time - last_rob < ROB_COOLDOWN:
            wait_time = ROB_COOLDOWN - (current_time - last_rob)
            return bot.reply_to(message, 
                f"⏳ рано! Следующая попытка через {int(wait_time//3600)} ч. {int((wait_time%3600)//60)} мин.")
            
        target_balance = get_balance(target_id)
        if target_balance < MIN_ROB:
            return bot.reply_to(message, 
                f"💼 У игрока недостаточно средств. Минимум для ограбления: {format_number(MIN_ROB)} zcoin")

        rob_amount = random.randint(MIN_ROB, min(MAX_ROB, target_balance))
        success = random.randint(1, 100) <= SUCCESS_CHANCE

        update_last_robbery(user_id)  # Обновляем таймер независимо от исхода

        if success:
            # Успешное ограбление
            update_balance(user_id, rob_amount)
            update_balance(target_id, -rob_amount)
            
            bot.reply_to(message,
                f"🎉 Успешное ограбление!\n"
                f"💸 Украдено: {format_number(rob_amount)} zcoin\n"
                f"👤 Жертва: @{target_user.username}\n"
                f"💼 Ваш баланс: {format_number(get_balance(user_id))} zcoin")
        else:
            # Неудачная попытка
            fine = int(rob_amount * FINE_PERCENT / 100)
            update_balance(user_id, -fine)
            
            bot.reply_to(message,
                f"💥 анлак! Вас поймали!\n"
                f"📉 Штраф: {format_number(fine)} zcoin\n"
                f"💼 Ваш баланс: {format_number(get_balance(user_id))} zcoin")

    except Exception as e:
        logging.error(f"Ошибка в /ограбить: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при попытке ограбления")
def update_last_robbery(user_id):
    conn = sqlite3.connect(DB_NAME)
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET last_robbery = ? WHERE user_id = ?", 
                 (int(time.time()), user_id))
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка обновления времени последнего ограбления: {str(e)}")
    finally:
        conn.close()

def handle_schedule(message):
    try:
        screenshot = get_screenshot()
        if screenshot:
            image = Image.open(BytesIO(screenshot))
            image = process_image(image)
            buf = BytesIO()
            image.save(buf, format='PNG')
            buf.seek(0)
            bot.send_photo(message.chat.id, photo=buf, caption="📅 Актуальное расписание")
        else:
            bot.reply_to(message, "❌ Не удалось получить расписание, попробуйте позже")
    except Exception as e:
        logging.error(f"Ошибка обработки расписания: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при получении расписания")
def format_number(number):
    """
    Форматирует число, добавляя точки каждые три цифры.
    Пример: 12345678 -> 12.345.678
    """
    return f"{number:,}".replace(",", ".")
class MineGame:
    def __init__(self, user_id, bet, bombs):
        self.user_id = user_id
        self.bet = bet
        self.bombs = bombs
        self.opened = set()
        self.multiplier = 1.0
        self.field = self.generate_field()
        self.game_over = False
        self.message_id = None

    def generate_field(self):
        cells = [False] * (MINEFIELD_SIZE**2 - self.bombs) + [True] * self.bombs
        random.shuffle(cells)
        return [cells[i*MINEFIELD_SIZE:(i+1)*MINEFIELD_SIZE] for i in range(MINEFIELD_SIZE)]

    def open_cell(self, x, y):
        if (x, y) in self.opened or self.game_over:
            return False
        
        self.opened.add((x, y))
        
        if self.field[x][y]:
            self.game_over = True
            return False
        
        opened = len(self.opened)
        total = MINEFIELD_SIZE**2 - self.bombs
        
        # Базовый множитель зависит от количества бомб
        # Чем меньше бомб, тем меньше базовый множитель
        base_multiplier = 1.0 + (self.bombs / MINEFIELD_SIZE**2) * 2.0
        
        # Прирост множителя за каждую открытую клетку
        # Чем меньше бомб, тем меньше прирост
        increment = (MAX_REWARD_MULTIPLIER - MIN_REWARD_MULTIPLIER) * (opened / total) * (self.bombs / MINEFIELD_SIZE**2)
        
        # Итоговый множитель
        self.multiplier = round(base_multiplier + increment, 2)
        
        return True

    def get_field_text(self):
        output = "🏴‍☠️ Игра «Сапер»\n"
        output += f"💣 Бомб: {self.bombs} | 💰 Ставка: {self.bet} zcoin\n"
        output += f"🎰 Множитель: x{self.multiplier:.2f} | 📍 Открыто: {len(self.opened)}\n\n"
        
        cell_number = 1
        for i in range(MINEFIELD_SIZE):
            row = []
            for j in range(MINEFIELD_SIZE):
                if (i, j) in self.opened:
                    row.append("💣" if self.field[i][j] else "✅")
                else:
                    row.append(f"{cell_number:02d}")
                cell_number += 1
            output += " | ".join(row) + "\n"
        
        output += "\nВведите номер клетки (01-25) или /вывод"
        return output
@bot.message_handler(commands=['передать'])
def handle_transfer(message):
    try:
        if not message.reply_to_message:
            bot.reply_to(message, "❌ Нужно ответить на сообщение пользователя, которому хотите перевести!")
            return

        sender_id = message.from_user.id
        receiver_id = message.reply_to_message.from_user.id

        if sender_id == receiver_id:
            bot.reply_to(message, "❌ Нельзя переводить самому себе!")
            return

        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "ℹ Формат: /передать [количество]")
            return
            
        try:
            amount = int(parts[1])
        except ValueError:
            bot.reply_to(message, "❌ Неверный формат суммы! Используйте целое число.")
            return

        if amount <= 0:
            bot.reply_to(message, "❌ Сумма должна быть больше нуля!")
            return

        commission = (amount * 5) // 100
        received = amount - commission

        if received <= 0:
            bot.reply_to(message, "❌ Сумма перевода после комиссии должна быть положительной!")
            return

        sender_balance = get_balance(sender_id)
        
        if sender_balance < amount:
            bot.reply_to(message, f"❌ Недостаточно средств! Ваш баланс: {sender_balance} zcoin")
            return

        conn = sqlite3.connect(DB_NAME)
        try:
            c = conn.cursor()
            c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", 
                     (amount, sender_id))
            c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (receiver_id,))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", 
                     (received, receiver_id))
            conn.commit()
            
            new_sender_balance = get_balance(sender_id)
            new_receiver_balance = get_balance(receiver_id)
            
            response = (
                f"✅ Перевод успешно выполнен!\n"
                f"┌ Отправлено: {amount} zcoin\n"
                f"├ Комиссия: {commission} zcoin (5%)\n"
                f"└ Получено: {received} zcoin\n\n"
                f"💼 Ваш новый баланс: {new_sender_balance} zcoin"
            )
            
            bot.reply_to(message, response)
            
            if message.chat.type == 'private':
                bot.send_message(
                    receiver_id,
                    f"💸 Вам перевели {received} zcoin!\n"
                    f"📦 Исходная сумма: {amount} zcoin\n"
                    f"📉 Вычтено комиссии: {commission} zcoin\n"
                    f"💼 Ваш новый баланс: {new_receiver_balance} zcoin"
                )
                
        except Exception as e:
            conn.rollback()
            bot.reply_to(message, f"🚫 Ошибка перевода: {str(e)}")
            
        finally:
            conn.close()

    except Exception as e:
        bot.reply_to(message, f"🚫 Ошибка: {str(e)}")

@bot.message_handler(commands=['баланс_добавить', 'баланс_отнять'])
def handle_balance_admin(message):
    # Убрана проверка на тип чата, оставлена только проверка на админа
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ У вас нет прав для выполнения этой команды")
        return

    try:
        # Исправленный парсинг команды
        parts = message.text.split()
        if len(parts) != 3:
            raise ValueError
            
        command = parts[0]
        target_id = int(parts[1])
        amount = int(parts[2])
        
        if amount <= 0:
            return bot.reply_to(message, "❌ Сумма должна быть больше нуля")

        current_balance = get_balance(target_id)
        
        if "отнять" in command:
            if current_balance < amount:
                return bot.reply_to(message, f"❌ Недостаточно средств у пользователя {target_id} (Баланс: {current_balance} zcoin)")
            
            update_balance(target_id, -amount)
            new_balance = current_balance - amount
            action = "отнято"
            emoji = "➖"
        else:
            update_balance(target_id, amount)
            new_balance = current_balance + amount
            action = "добавлено"
            emoji = "➕"

        bot.reply_to(message, 
            f"{emoji} Успешно {action} {amount} zcoin\n"
            f"👤 Пользователь: {target_id}\n"
            f"💰 Новый баланс: {new_balance} zcoin")
            
    except ValueError:
        bot.reply_to(message, "ℹ Формат команды:\n"
                              "/баланс_добавить [ID_пользователя] [сумма]\n"
                              "/баланс_отнять [ID_пользователя] [сумма]")
    except Exception as e:
        bot.reply_to(message, f"🚫 Ошибка: {str(e)}")
def get_weather(city):
    url = "https://api.weatherapi.com/v1/current.json"
    params = {
        "key": WEATHERAPI_KEY,
        "q": city,
        "lang": "ru"
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        if response.status_code == 200:
            return {
                'city': data['location']['name'],
                'temp': data['current']['temp_c'],
                'feels_like': data['current']['feelslike_c'],
                'condition': data['current']['condition']['text'],
                'wind': round(data['current']['wind_kph'] / 3.6, 1),
                'humidity': data['current']['humidity']
            }
        else:
            print(f"Ошибка: {data.get('error', {}).get('message')}")
            return None

    except Exception as e:
        print(f"API Error: {str(e)}")
        return None


@bot.message_handler(commands=['погода'])
def handle_weather(message):
    forward_to_admin(message)

    try:
        city = message.text.split(' ', 1)[1].strip()
        weather = get_weather(city)

        if weather:
            response = (
                f"🌤 Погода в {weather['city']}:\n"
                f"• Температура: {weather['temp']}°C\n"
                f"• Ощущается как: {weather['feels_like']}°C\n"
                f"• Состояние: {weather['condition']}\n"
                f"• Ветер: {weather['wind']} м/с\n"
                f"• Влажность: {weather['humidity']}%"
            )
            bot.reply_to(message, response)
        else:
            bot.reply_to(message, "🚫 Не удалось получить данные. Проверьте название города!")
    except IndexError:
        bot.reply_to(message, "ℹ Пример использования: /погода Москва")

# Функции работы с базой данных
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                (user_id INTEGER PRIMARY KEY, 
                 balance INTEGER DEFAULT 0,
                 username TEXT,
                 first_name TEXT,
                 last_name TEXT,
                 last_work INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS checks 
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 amount INTEGER,
                 password TEXT,
                 is_used INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS requests 
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 amount INTEGER,
                 status TEXT DEFAULT 'pending',
                 timestamp INTEGER)''')
    conn.commit()
    conn.close()
@bot.message_handler(commands=['запрос'])
def handle_request(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()
        
        if len(args) != 2:
            return bot.reply_to(message, "ℹ Используйте: /запрос [сумма]")
            
        try:
            amount = int(args[1])
            if amount <= 0:
                return bot.reply_to(message, "❌ Сумма должна быть больше нуля!")
        except ValueError:
            return bot.reply_to(message, "❌ Некорректная сумма!")
            
        # Проверка времени последнего запроса
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT timestamp FROM requests WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1", (user_id,))
        last_request = c.fetchone()
        
        if last_request and (time.time() - last_request[0] < REQUEST_COOLDOWN):
            wait_time = REQUEST_COOLDOWN - (time.time() - last_request[0])
            return bot.reply_to(message, 
                f"⏳ Следующий запрос можно будет отправить через {int(wait_time//3600)} ч. {int((wait_time%3600)//60)} мин.")
        
        # Сохраняем запрос
        c.execute("INSERT INTO requests (user_id, amount, timestamp) VALUES (?, ?, ?)",
                (user_id, amount, int(time.time())))
        request_id = c.lastrowid
        conn.commit()
        
        # Формируем сообщение для админа
        user = message.from_user
        admin_msg = (
            f"🆕 Новый запрос средств\n"
            f"🆔 ID запроса: {request_id}\n"
            f"👤 Пользователь: @{user.username} ({user.id})\n"
            f"💰 Сумма: {format_number(amount)} zcoin\n\n"
            f"Для обработки запроса используйте команды:\n"
            f"/принять_{request_id} - одобрить запрос\n"
            f"/отклонить_{request_id} - отклонить запрос"
        )
        
        bot.send_message(ADMIN_ID, admin_msg)
        bot.reply_to(message, "✅ Запрос отправлен администратору")

    except Exception as e:
        logging.error(f"Ошибка запроса средств: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при обработке запроса")
    finally:
        conn.close()

# Обработчик команды /принять
@bot.message_handler(commands=['принять'])
def handle_accept_request(message):
    try:
        if message.from_user.id != ADMIN_ID:
            return bot.reply_to(message, "⛔ У вас нет прав на выполнение этой команды!")
            
        request_id = int(message.text.split('_')[1])
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id, amount, status FROM requests WHERE id = ?", (request_id,))
        request = c.fetchone()
        
        if not request:
            return bot.reply_to(message, "❌ Запрос не найден!")
            
        user_id, amount, status = request
        
        if status != 'pending':
            return bot.reply_to(message, "⚠ Запрос уже обработан!")
            
        # Обновляем статус запроса и баланс пользователя
        update_balance(user_id, amount)
        c.execute("UPDATE requests SET status = 'approved' WHERE id = ?", (request_id,))
        conn.commit()
        
        # Уведомляем пользователя
        try:
            bot.send_message(user_id, f"✅ Ваш запрос на {format_number(amount)} zcoin одобрен!")
        except Exception as e:
            logging.error(f"Не удалось уведомить пользователя {user_id}: {str(e)}")
        
        bot.reply_to(message, f"✅ Запрос #{request_id} одобрен. Пользователю @{bot.get_chat(user_id).username} зачислено {format_number(amount)} zcoin.")

    except Exception as e:
        logging.error(f"Ошибка обработки запроса: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при обработке запроса")
    finally:
        conn.close()

# Обработчик команды /отклонить
@bot.message_handler(commands=['отклонить'])
def handle_reject_request(message):
    try:
        if message.from_user.id != ADMIN_ID:
            return bot.reply_to(message, "⛔ У вас нет прав на выполнение этой команды!")
            
        request_id = int(message.text.split('_')[1])
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id, amount, status FROM requests WHERE id = ?", (request_id,))
        request = c.fetchone()
        
        if not request:
            return bot.reply_to(message, "❌ Запрос не найден!")
            
        user_id, amount, status = request
        
        if status != 'pending':
            return bot.reply_to(message, "⚠ Запрос уже обработан!")
            
        # Обновляем статус запроса
        c.execute("UPDATE requests SET status = 'rejected' WHERE id = ?", (request_id,))
        conn.commit()
        
        # Уведомляем пользователя
        try:
            bot.send_message(user_id, f"❌ Ваш запрос на {format_number(amount)} zcoin отклонен.")
        except Exception as e:
            logging.error(f"Не удалось уведомить пользователя {user_id}: {str(e)}")
        
        bot.reply_to(message, f"❌ Запрос #{request_id} отклонен.")

    except Exception as e:
        logging.error(f"Ошибка обработки запроса: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при обработке запроса")
    finally:
        conn.close()
def migrate_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        # Добавляем колонку last_work, если её нет
        c.execute("ALTER TABLE users ADD COLUMN last_work INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует
    # Обновляем существующие записи с NULL в last_work на 0
    c.execute("UPDATE users SET last_work = 0 WHERE last_work IS NULL")
    try:
        # Аналогично для last_robbery
        c.execute("ALTER TABLE users ADD COLUMN last_robbery INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    c.execute("UPDATE users SET last_robbery = 0 WHERE last_robbery IS NULL")
    conn.commit()
    conn.close()

def update_user_info(user):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO users 
                    (user_id, username, first_name, last_name, balance, last_work, last_robbery) 
                    VALUES (?, ?, ?, ?, 
                    COALESCE((SELECT balance FROM users WHERE user_id = ?), 0),
                    COALESCE((SELECT last_work FROM users WHERE user_id = ?), 0),
                    COALESCE((SELECT last_robbery FROM users WHERE user_id = ?), 0))''',
                (user.id, 
                 user.username or None,
                 user.first_name or None,
                 user.last_name or None,
                 user.id,
                 user.id,
                 user.id))
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка обновления пользователя: {str(e)}")
    finally:
        conn.close()

def get_balance(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def update_balance(user_id, amount):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка обновления баланса: {str(e)}")
    finally:
        conn.close()

def get_last_work(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT last_work FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result and result[0] is not None else 0

def update_last_work(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET last_work = ? WHERE user_id = ?", 
             (int(time.time()), user_id))
    conn.commit()
    conn.close()

# Основные команды бота
@bot.message_handler(commands=['start'])
def handle_start(message):
    update_user_info(message.from_user)
    bot.reply_to(message, "👋 Добро пожаловать в ZCoin Бот!\n"
                          "Доступные команды:\n"
                          "/баланс - Проверить баланс\n"
                          "/работа - Заработать zcoin\n"
                          "/минер - Играть в Сапера\n"
                          "/передать - Перевести средства\n"
                          "/расписание - расписание пар\n"
                          "/погода - Узнать погоду")

@bot.message_handler(commands=['баланс'])
def handle_balance(message):
    try:
        if message.reply_to_message:
            user_id = message.reply_to_message.from_user.id
            username = message.reply_to_message.from_user.username or message.reply_to_message.from_user.first_name
            balance = get_balance(user_id)
            bot.reply_to(message, f"💰 Баланс пользователя @{username}: {format_number(balance)} zcoin")
        else:
            user_id = message.from_user.id
            balance = get_balance(user_id)
            bot.reply_to(message, f"💰 Ваш баланс: {format_number(balance)} zcoin")
    except Exception as e:
        logging.error(f"Ошибка в обработке команды /баланс: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при получении баланса")

@bot.message_handler(commands=['работа'])
def handle_work(message):
    user_id = message.from_user.id
    last_work = get_last_work(user_id)
    current_time = time.time()

    if current_time - last_work < WORK_COOLDOWN:
        wait_time = WORK_COOLDOWN - (current_time - last_work)
        minutes = int(wait_time // 60)
        seconds = int(wait_time % 60)
        bot.reply_to(message, f"⏳ Рано! Приходи через {minutes} мин. {seconds} сек.")
        return

    reward = random.randint(MIN_REWARD, MAX_REWARD)
    update_balance(user_id, reward)
    update_last_work(user_id)

    work_messages = [
        f"🍜 Ты потрудился в Zшаурмичной и заработал {format_number(reward)} zcoin!",
        f"🧑🍳 За смену завернул {random.randint(10, 50)} шаурм! Получено {format_number(reward)} zcoin!",
        f"💪 Заработал {format_number(reward)} zcoin {random.choice(['борясь с фанатами', 'убирая столы'])}!"
    ]

    bot.reply_to(message,
                 f"{random.choice(work_messages)}\n"
                 f"💼 Твой баланс: {format_number(get_balance(user_id))} zcoin")

@bot.message_handler(commands=['минер'])
def handle_mine(message):
    try:
        user_id = message.from_user.id
        args = message.text.split()

        if len(args) != 3:
            return bot.reply_to(message, "ℹ Используйте: /минер [1-20] [ставка|все]")

        bombs = int(args[1])
        bet_arg = args[2]

        if not (1 <= bombs <= 20):
            return bot.reply_to(message, "❌ Число бомб должно быть 1-20")

        # Проверяем, хочет ли пользователь поставить весь баланс
        if bet_arg.lower() == 'все':
            bet = get_balance(user_id)
            if bet <= 0:
                return bot.reply_to(message, "❌ Ваш баланс равен нулю или отрицательный!")
        else:
            try:
                bet = int(bet_arg)
            except ValueError:
                return bot.reply_to(message, "❌ Некорректное значение ставки! Используйте число или 'все'.")

        if get_balance(user_id) < bet:
            return bot.reply_to(message, f"❌ Недостаточно средств! Баланс: {format_number(get_balance(user_id))} zcoin")

        if user_id in active_games:
            del active_games[user_id]

        update_balance(user_id, -bet)
        game = MineGame(user_id, bet, bombs)
        active_games[user_id] = game

        msg = bot.send_message(
            message.chat.id,
            game.get_field_text()
        )
        game.message_id = msg.message_id

    except ValueError:
        bot.reply_to(message, "❌ Некорректные числовые значения")
    except Exception as e:
        logging.error(f"Ошибка в /минер: {str(e)}")
        bot.reply_to(message, "🚫 Произошла ошибка при создании игры")


@bot.message_handler(commands=['вывод'])
def handle_cashout(message):
    user_id = message.from_user.id
    game = active_games.get(user_id)

    if not game:
        return bot.reply_to(message, "❌ Нет активной игры!")

    if game.game_over:
        return bot.reply_to(message, "🚫 Игра уже завершена!")

    win_amount = int(game.bet * game.multiplier)
    update_balance(user_id, win_amount)
    del active_games[user_id]

    try:
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=game.message_id,
            text=f"🎉 Успешный вывод!\n"
                 f"💸 Выигрыш: {format_number(win_amount)} zcoin\n"
                 f"💰 Ставка: {format_number(game.bet)} zcoin\n"
                 f"📈 Множитель: x{game.multiplier:.2f}"
        )
    except Exception as e:
        logging.error(f"Ошибка редактирования сообщения: {str(e)}")

    bot.send_message(
        message.chat.id,
        f"✅ Получено {format_number(win_amount)} zcoin!\n"
        f"💼 Ваш баланс: {format_number(get_balance(user_id))} zcoin"
    )

# Обработка быстрых фраз и расписания
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_all_messages(message):
    try:
        user_id = message.from_user.id
        update_user_info(message.from_user)
        text = message.text.strip().lower()
        
        # Проверка активной игры
        if user_id in active_games:
            game = active_games[user_id]
            
            # Обработка вывода
            if text == '/вывод':
                handle_cashout(message)
                return
                
            # Парсинг номера клетки
            try:
                cell_num = int(text)
                if not (1 <= cell_num <= MINEFIELD_SIZE**2):
                    raise ValueError
            except ValueError:
                bot.reply_to(message, f"❌ Введите число от 01 до {MINEFIELD_SIZE**2:02d}")
                return
                
            # Конвертация номера в координаты
            cell_num -= 1  # Переводим в 0-based индекс
            x = cell_num // MINEFIELD_SIZE
            y = cell_num % MINEFIELD_SIZE
            
            # Открываем клетку
            if not game.open_cell(x, y):
                if game.game_over:
                    # Обработка проигрыша
                    update_balance(user_id, 0)
                    del active_games[user_id]
                    bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=game.message_id,
                        text=f"💥 БОМБА! Вы проиграли {game.bet} zcoin!\n"
                             "Попробуйте еще раз /минер"
                    )
                    return
                else:
                    bot.reply_to(message, "❌ Клетка уже открыта")
                    return
                    
            # Обновляем сообщение с полем
            try:
                bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=game.message_id,
                    text=game.get_field_text()
                )
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения: {str(e)}")
                
            return
        # Обработка быстрых фраз
        commands = {
            "сосал?": "Да",
            "сосал": "Да",
            "пизда": "эх",
            "когда дс": "никогда",
            "когда шарага": "никогда",
            "когда нахуй пойдешь": "никогда",
            "когда будешь нормальным?": "никогда",
            "идешь в бургер кинг?": "нет",
            "соси": "сам",
            "почему?": "я кататься поеду",
            "кто шлюха?": "я",
            "кто любит випс?": "випс хуйня",
            "кто чебуреки дома поедает?": "яяя"
        }

        for phrase in commands:
            if phrase in text:
                bot.reply_to(message, commands[phrase])
                return

        # Проверка расписания
        if any(word in text for word in ['расписание', 'расписания', 'пары']):
            handle_schedule(message)
            return
            
        # Если сообщение не обработано, добавляем в список
        user_messages.append(message.text)
        
    except Exception as e:
        logging.error(f"Ошибка в обработке сообщения: {str(e)}")

# Остальные функции
@bot.message_handler(commands=['передать'])
def handle_transfer(message):
    try:
        if not message.reply_to_message:
            bot.reply_to(message, "❌ Нужно ответить на сообщение пользователя, которому хотите перевести!")
            return

        sender_id = message.from_user.id
        receiver_id = message.reply_to_message.from_user.id

        if sender_id == receiver_id:
            bot.reply_to(message, "❌ Нельзя переводить самому себе!")
            return

        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "ℹ Формат: /передать [количество]")
            return

        try:
            amount = int(parts[1])
        except ValueError:
            bot.reply_to(message, "❌ Неверный формат суммы! Используйте целое число.")
            return

        if amount <= 0:
            bot.reply_to(message, "❌ Сумма должна быть больше нуля!")
            return

        commission = (amount * 5) // 100
        received = amount - commission

        if received <= 0:
            bot.reply_to(message, "❌ Сумма перевода после комиссии должна быть положительной!")
            return

        sender_balance = get_balance(sender_id)

        if sender_balance < amount:
            bot.reply_to(message, f"❌ Недостаточно средств! Ваш баланс: {format_number(sender_balance)} zcoin")
            return

        conn = sqlite3.connect(DB_NAME)
        try:
            c = conn.cursor()
            c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?",
                     (amount, sender_id))
            c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (receiver_id,))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                     (received, receiver_id))
            conn.commit()

            new_sender_balance = get_balance(sender_id)
            new_receiver_balance = get_balance(receiver_id)

            response = (
                f"✅ Перевод успешно выполнен!\n"
                f"┌ Отправлено: {format_number(amount)} zcoin\n"
                f"├ Комиссия: {format_number(commission)} zcoin (5%)\n"
                f"└ Получено: {format_number(received)} zcoin\n\n"
                f"💼 Ваш новый баланс: {format_number(new_sender_balance)} zcoin"
            )

            bot.reply_to(message, response)

            if message.chat.type == 'private':
                bot.send_message(
                    receiver_id,
                    f"💸 Вам перевели {format_number(received)} zcoin!\n"
                    f"📦 Исходная сумма: {format_number(amount)} zcoin\n"
                    f"📉 Вычтено комиссии: {format_number(commission)} zcoin\n"
                    f"💼 Ваш новый баланс: {format_number(new_receiver_balance)} zcoin"
                )

        except Exception as e:
            conn.rollback()
            bot.reply_to(message, f"🚫 Ошибка перевода: {str(e)}")

        finally:
            conn.close()

    except Exception as e:
        bot.reply_to(message, f"🚫 Ошибка: {str(e)}")



def get_screenshot():
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--window-size=1280,720")
        chrome_options.add_argument("--force-device-scale-factor=2.0")
        chrome_options.add_argument("--high-dpi-support=1")
        chrome_options.add_argument("--disable-font-subpixel-positioning")

        chrome_options.add_experimental_option("prefs", {
            "webkit.font_rendering": "subpixel",
            "font_rendering_metric_compatibility": "1"
        })

        driver = webdriver.Chrome(options=chrome_options)
        driver.get(SCHEDULE_URL)
        time.sleep(5)

        total_height = driver.execute_script("return document.body.scrollHeight")
        driver.set_window_size(1280, total_height)

        screenshot = driver.get_screenshot_as_png()
        driver.quit()

        return screenshot
    except Exception as e:
        print(f"Ошибка при создании скриншота: {e}")
        return None


def process_image(image):
    width, height = image.size
    image = image.crop((0, 0, width, height - 100))
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(1.2)
    enhancer = ImageEnhance.Sharpness(image)
    image = enhancer.enhance(1.5)
    image = image.filter(ImageFilter.EDGE_ENHANCE_MORE)
    image = image.resize((int(width * 0.8), int(height * 0.8)), Image.LANCZOS)
    return image



def scheduled_send():
    screenshot = get_screenshot()
    if screenshot:
        image = Image.open(BytesIO(screenshot))
        image = process_image(image)
        buf = BytesIO()
        image.save(buf, format='PNG')
        buf.seek(0)

        for group_id in GROUP_IDS:
            bot.send_photo(group_id, photo=buf, caption="Ежедневное обновление расписания")

schedule.every().day.at("20:00").do(scheduled_send)

def scheduler_thread():
    while True:
        schedule.run_pending()
        time.sleep(1)

threading.Thread(target=scheduler_thread, daemon=True).start()

if __name__ == '__main__':
    init_db()
    migrate_db()
    logging.info("Бот запущен")
    bot.infinity_polling()

