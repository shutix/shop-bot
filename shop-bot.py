import telebot
from telebot import types
import sqlite3
import threading
import time
import requests

# import andro_cfw
# andro_cfw.patch() 

# ============================================================
#   🔑  НАСТРОЙКИ
# ============================================================

import os
TOKEN = os.environ.get("TOKEN")
CRYPTO_TOKEN = os.environ.get("CRYPTO_TOKEN")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x]
# курс USDT и установка прайса
USDT_TO_RUB = 83.83
RATE_UPDATE_INTERVAL = 3600
MIN_TOPUP = 10
MAX_TOPUP = 100000

# ============================================================

bot = telebot.TeleBot(TOKEN)
CRYPTO_API_URL = "https://pay.crypt.bot/api/"


# ============================================================
#   🗄️  БАЗА ДАННЫХ
# ============================================================

conn = sqlite3.connect('shop.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    balance INTEGER DEFAULT 0,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    invoice_id INTEGER,
    amount_rub INTEGER,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    message_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product_id INTEGER,
    product_name TEXT,
    price INTEGER,
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount INTEGER,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')
conn.commit()

# --- Миграция ---
cursor.execute("PRAGMA table_info(users)")
_columns = [row[1] for row in cursor.fetchall()]
if "balance" not in _columns:
    cursor.execute("ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0")
    conn.commit()
    print("[БД] ✅ Добавлена колонка balance в users")
else:
    print("[БД] ✅ Колонка balance уже существует")


# --- Пользователи ---
def add_user(user_id, username, first_name):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
        (user_id, username, first_name)
    )
    conn.commit()


def get_total_users():
    cursor.execute("SELECT COUNT(*) FROM users")
    return cursor.fetchone()[0]


def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0


def add_balance(user_id, amount):
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()


def subtract_balance(user_id, amount):
    cursor.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()


# --- Заказы ---
def create_order(user_id, invoice_id, amount_rub):
    cursor.execute(
        "INSERT INTO orders (user_id, invoice_id, amount_rub) VALUES (?, ?, ?)",
        (user_id, invoice_id, amount_rub)
    )
    conn.commit()


def get_order_status(invoice_id):
    cursor.execute("SELECT status FROM orders WHERE invoice_id = ?", (invoice_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def mark_order_paid(invoice_id):
    cursor.execute(
        "UPDATE orders SET status = 'paid' WHERE invoice_id = ?",
        (invoice_id,)
    )
    conn.commit()


# --- Товары ---
def add_product(name, price, message_text):
    cursor.execute(
        "INSERT INTO products (name, price, message_text) VALUES (?, ?, ?)",
        (name, price, message_text)
    )
    conn.commit()
    return cursor.lastrowid


def get_products():
    cursor.execute("SELECT id, name, price FROM products ORDER BY id")
    return cursor.fetchall()


def get_product(product_id):
    cursor.execute(
        "SELECT id, name, price, message_text FROM products WHERE id = ?",
        (product_id,)
    )
    return cursor.fetchone()


def delete_product(product_id):
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()


# --- Покупки ---
def add_purchase(user_id, product_id, product_name, price):
    cursor.execute(
        "INSERT INTO purchases (user_id, product_id, product_name, price) VALUES (?, ?, ?, ?)",
        (user_id, product_id, product_name, price)
    )
    conn.commit()


def get_user_purchases(user_id):
    cursor.execute(
        "SELECT product_name, price, purchased_at FROM purchases WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    )
    return cursor.fetchall()


def get_all_purchases(limit=50):                       # ← ВСТАВИТЬ СЮДА
    """Возвращает последние N покупок всех пользователей."""  # ← ВСТАВИТЬ СЮДА
    cursor.execute(                                     # ← ВСТАВИТЬ СЮДА
        "SELECT user_id, product_name, price, purchased_at FROM purchases ORDER BY id DESC LIMIT ?",  # ← ВСТАВИТЬ СЮДА
        (limit,)                                        # ← ВСТАВИТЬ СЮДА
    )                                                   # ← ВСТАВИТЬ СЮДА
    return cursor.fetchall()                            # ← ВСТАВИТЬ СЮДА


# --- Транзакции ---
def add_transaction(user_id, type_, amount, description):
    cursor.execute(
        "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
        (user_id, type_, amount, description)
    )
    conn.commit()


def get_user_transactions(user_id, limit=20):
    cursor.execute(
        "SELECT type, amount, description, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    return cursor.fetchall()


# ============================================================
#   💳  CRYPTOBOT API
# ============================================================

def crypto_create_invoice(amount_usdt, description, payload):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {
        "asset": "USDT",
        "amount": str(amount_usdt),
        "description": description,
        "payload": payload,
        "expires_in": 3600,
    }
    response = requests.post(
        CRYPTO_API_URL + "createInvoice",
        headers=headers,
        json=data,
        timeout=15
    )
    result = response.json()
    if result.get("ok"):
        return result["result"]
    else:
        raise Exception(f"CryptoBot error: {result}")


def crypto_get_invoice(invoice_id):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    response = requests.get(
        CRYPTO_API_URL + "getInvoices",
        headers=headers,
        params={"invoice_ids": str(invoice_id)},
        timeout=15
    )
    result = response.json()
    if result.get("ok") and result["result"]["items"]:
        return result["result"]["items"][0]
    return None


# ============================================================
#   💱  АВТООБНОВЛЕНИЕ КУРСА
# ============================================================

def get_usdt_rub_rate():
    global USDT_TO_RUB
    try:
        headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
        response = requests.get(
            CRYPTO_API_URL + "getExchangeRates",
            headers=headers,
            timeout=15
        )
        result = response.json()
        if result.get("ok"):
            for rate in result["result"]:
                if rate.get("source") == "USDT" and rate.get("target") == "RUB":
                    USDT_TO_RUB = float(rate["rate"])
                    print(f"[КУРС] USDT/RUB обновлён: {USDT_TO_RUB}")
                    return USDT_TO_RUB
    except Exception as e:
        print(f"[КУРС] Ошибка обновления: {e}")
    return USDT_TO_RUB


def rate_updater():
    while True:
        get_usdt_rub_rate()
        time.sleep(RATE_UPDATE_INTERVAL)


# ============================================================
#   ✏️  ТЕКСТЫ
# ============================================================

TEXTS = {
    "purchases": (
        "🛒 *Мои покупки*\n\n"
        "Здесь будет отображаться история ваших покупок."
    ),
    "faq": (
        "❓ *Часто задаваемые вопросы*\n\n"
        "*1. Как купить товар?*\n"
        "Пополните баланс, зайдите в магазин и нажмите «Купить».\n\n"
        "*2. Как оплатить?*\n"
        "Оплата проходит через крипту (USDT).\n\n"
        "*3. Есть ли гарантия?*\n"
        "67."
    ),
    "main_menu": "Я бот YTprimehub_SHOP \nВыбери действие:",
}


def get_topup_text():
    return (
        "💳 *Пополнение баланса*\n\n"
        f"Напишите сумму пополнения в рублях (только цифры).\n"
        f"Минимум — {MIN_TOPUP} ₽\n"
        f"Курс: 1 USDT ≈ {round(USDT_TO_RUB, 2)} ₽\n\n"
        f"Например: `500`"
    )


# ============================================================
#   🔘  КНОПКИ
# ============================================================

def get_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🛍 Открыть магазин", callback_data="open_shop"),
        types.InlineKeyboardButton("🛒 Мои покупки", callback_data="purchases")
    )
    markup.add(
        types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        types.InlineKeyboardButton("📜 История", callback_data="history")
    )
    markup.add(
        types.InlineKeyboardButton("❓ FAQ", callback_data="faq"),
        types.InlineKeyboardButton("💳 Пополнить баланс", callback_data="top_up")
    )
    markup.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="count_accounts"),
        types.InlineKeyboardButton("🌐 Наш канал", url="https://t.me/+dM0pt63TkIA2OTky")
    )
    return markup


def get_back_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="main_menu"))
    return markup


def get_shop_menu():
    products = get_products()
    markup = types.InlineKeyboardMarkup(row_width=1)

    if not products:
        markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="main_menu"))
        return markup

    for pid, name, price in products:
        markup.add(types.InlineKeyboardButton(
            f"🛍 {name} — {price} ₽",
            callback_data=f"view_product_{pid}"
        ))
    markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="main_menu"))
    return markup


# ============================================================
#   🤖  КОМАНДЫ
# ============================================================

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    username = message.from_user.username or "без_юзернейма"

    add_user(user_id, username, name)


    bot.send_message(
        message.chat.id,
        TEXTS["main_menu"],
        reply_markup=get_main_menu()
    )


@bot.message_handler(commands=['help'])
def help_command(message):
    text = (
        "📖 Доступные команды:\n\n"
        "/start — запустить бота\n"
        "/help — эта справка\n"
        "/rate — текущий курс USDT\n"
    )
    if message.from_user.id in ADMIN_IDS:
        text += (
            "\n👑 Админ-команды:\n"
            "/add_product — добавить товар\n"
            "/list_products — список товаров\n"
            "/del_product — удалить товар\n"
            "/add_balance — пополнить баланс пользователю\n"
            "/del_balance — списать баланс у пользователя\n"
            "/purchases_all - список всех покупок\n"
            "/user_purchases ID - список покупок пользователя\n"
        )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['rate'])
def rate_command(message):
    bot.send_message(
        message.chat.id,
        f"💱 Текущий курс: 1 USDT ≈ {round(USDT_TO_RUB, 2)} ₽"
    )


# ============================================================
#   👑  АДМИН-КОМАНДЫ
# ============================================================

@bot.message_handler(commands=['add_product'])
def admin_add_product(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "⛔ У вас нет доступа.")
        return
    msg = bot.send_message(
        message.chat.id,
        "📝 Введите *название товара* (например, «YouTube аккаунт 2015»):",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, add_product_step2)


def add_product_step2(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    name = message.text.strip()
    msg = bot.send_message(
        message.chat.id,
        f"Название: *{name}*\n\n💵 Введите *цену в рублях* (только цифры):",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, add_product_step3, name)


def add_product_step3(message, name):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not message.text.strip().isdigit():
        bot.send_message(message.chat.id, "❌ Цена должна быть целым числом. Начните заново: /add_product")
        return
    price = int(message.text.strip())
    msg = bot.send_message(
        message.chat.id,
        f"Цена: *{price} ₽*\n\n🎁 Введите *текст, который получит покупатель* после оплаты:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, add_product_step4, name, price)


def add_product_step4(message, name, price):
    if message.from_user.id not in ADMIN_IDS:
        return
    message_text = message.text
    product_id = add_product(name, price, message_text)
    bot.send_message(
        message.chat.id,
        f"✅ Товар добавлен!\n\n"
        f"🆔 ID: `{product_id}`\n"
        f"📦 Название: *{name}*\n"
        f"💵 Цена: *{price} ₽*",
        parse_mode='Markdown'
    )


@bot.message_handler(commands=['list_products'])
def admin_list_products(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    products = get_products()
    if not products:
        bot.send_message(message.chat.id, "📦 Список товаров пуст.")
        return

    text = "📦 Список товаров:\n\n"
    for pid, name, price in products:
        text += f"{pid} — {name} — {price} ₽\n"
    text += "\nЧтобы удалить: /del_product"

    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['del_product'])
def admin_del_product(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    msg = bot.send_message(message.chat.id, "Введите ID товара для удаления:")
    bot.register_next_step_handler(msg, del_product_step)


def del_product_step(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not message.text.strip().isdigit():
        bot.send_message(message.chat.id, "❌ Нужно ввести ID (число).")
        return
    pid = int(message.text.strip())
    product = get_product(pid)
    if not product:
        bot.send_message(message.chat.id, "❌ Товар не найден.")
        return
    delete_product(pid)
    bot.send_message(message.chat.id, f"✅ Товар «{product[1]}» удалён.")


@bot.message_handler(commands=['add_balance'])
def admin_add_balance(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "⛔ У вас нет доступа.")
        return
    msg = bot.send_message(
        message.chat.id,
        "💰 Введите *ID пользователя* и *сумму* через пробел.\n\n"
        "Пример: `5566395763 500`\n\n"
        "Свой ID можно посмотреть в профиле бота.\n"
        "Свой ID: `" + str(message.from_user.id) + "`",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, add_balance_step)


def add_balance_step(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError
        target_id = int(parts[0])
        amount = int(parts[1])
        if amount <= 0:
            raise ValueError

        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (target_id,))
        if not cursor.fetchone():
            bot.send_message(
                message.chat.id,
                f"❌ Пользователь с ID `{target_id}` не найден в базе.",
                parse_mode='Markdown'
            )
            return

        add_balance(target_id, amount)
        add_transaction(target_id, "topup", amount, "Пополнение администратором")
        new_balance = get_balance(target_id)

        bot.send_message(
            message.chat.id,
            f"✅ Баланс пополнен!\n\n"
            f"👤 Пользователь: `{target_id}`\n"
            f"➕ Сумма: *{amount} ₽*\n"
            f"💰 Новый баланс: *{new_balance} ₽*",
            parse_mode='Markdown'
        )

        if target_id not in ADMIN_IDS:
            try:
                bot.send_message(
                    target_id,
                    f"💰 Вам зачислено *{amount} ₽*.\n"
                    f"Текущий баланс: *{new_balance} ₽*",
                    parse_mode='Markdown'
                )
            except Exception:
                pass

    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ Неверный формат.\nИспользуйте: `/add_balance` → `ID сумма`",
            parse_mode='Markdown'
        )


@bot.message_handler(commands=['del_balance'])
def admin_del_balance(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "⛔ У вас нет доступа.")
        return
    msg = bot.send_message(
        message.chat.id,
        "💸 Введите *ID пользователя* и *сумму* для списания через пробел.\n\n"
        "Пример: `5566395763 100`",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, del_balance_step)


def del_balance_step(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError
        target_id = int(parts[0])
        amount = int(parts[1])
        if amount <= 0:
            raise ValueError

        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (target_id,))
        if not cursor.fetchone():
            bot.send_message(
                message.chat.id,
                f"❌ Пользователь с ID `{target_id}` не найден.",
                parse_mode='Markdown'
            )
            return

        current = get_balance(target_id)
        if current < amount:
            bot.send_message(
                message.chat.id,
                f"❌ У пользователя только *{current} ₽*. Нельзя списать *{amount} ₽*.",
                parse_mode='Markdown'
            )
            return

        subtract_balance(target_id, amount)
        add_transaction(target_id, "purchase", -amount, "Списание администратором")
        new_balance = get_balance(target_id)

        bot.send_message(
            message.chat.id,
            f"✅ Баланс списан!\n\n"
            f"👤 Пользователь: `{target_id}`\n"
            f"➖ Сумма: *{amount} ₽*\n"
            f"💰 Новый баланс: *{new_balance} ₽*",
            parse_mode='Markdown'
        )

        if target_id not in ADMIN_IDS:
            try:
                bot.send_message(
                    target_id,
                    f"⚠️ С вашего баланса списано *{amount} ₽*.\n"
                    f"Текущий баланс: *{new_balance} ₽*",
                    parse_mode='Markdown'
                )
            except Exception:
                pass

    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ Неверный формат.\nИспользуйте: `/del_balance` → `ID сумма`",
            parse_mode='Markdown'
        )

# --- увилеть все покупки ---
@bot.message_handler(commands=['purchases_all'])
def admin_all_purchases(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "⛔ У вас нет доступа.")
        return

    purchases = get_all_purchases(50)

    if not purchases:
        bot.send_message(message.chat.id, "🛒 Покупок пока нет.")
        return

    text = "🛒 *Все покупки* (последние 50):\n\n"
    total_sum = 0
    for user_id, name, price, purchased in purchases:
        text += (
            f"👤 `{user_id}` — *{name}* — *{price} ₽*\n"
            f"🕐 _{purchased}_\n\n"
        )
        total_sum += price

    text += f"\n💰 *Общая сумма:* {total_sum} ₽\n"
    text += f"📦 *Всего покупок:* {len(purchases)}"

    bot.send_message(message.chat.id, text, parse_mode='Markdown')


# --- увидеть окупки конкретного пользователя ---
@bot.message_handler(commands=['user_purchases'])
def admin_user_purchases(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "⛔ У вас нет доступа.")
        return

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        bot.send_message(
            message.chat.id,
            "❌ Использование: `/user_purchases ID`\n"
            "Пример: `/user_purchases 5566395763`",
            parse_mode='Markdown'
        )
        return

    target_id = int(parts[1])

    cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (target_id,))
    user = cursor.fetchone()

    if not user:
        bot.send_message(
            message.chat.id,
            f"❌ Пользователь с ID `{target_id}` не найден.",
            parse_mode='Markdown'
        )
        return

    purchases = get_user_purchases(target_id)

    if not purchases:
        bot.send_message(
            message.chat.id,
            f"🛒 У пользователя `{target_id}` ({user[0]}) нет покупок.",
            parse_mode='Markdown'
        )
        return

    text = f"🛒 *Покупки пользователя* `{target_id}` ({user[0]}):\n\n"
    total = 0
    for name, price, purchased in purchases:
        text += f"📦 *{name}* — {price} ₽\n_{purchased}_\n\n"
        total += price

    text += f"\n💰 *Всего потрачено:* {total} ₽\n"
    text += f"📦 *Всего покупок:* {len(purchases)}"

    bot.send_message(message.chat.id, text, parse_mode='Markdown')



# ============================================================
#   🖱️  ОБРАБОТКА КНОПОК
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    data = call.data
    user_id = call.from_user.id

    # --- Назад в меню ---
    if data == "main_menu":
        bot.edit_message_text(
            TEXTS["main_menu"],
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_main_menu()
        )
        bot.answer_callback_query(call.id)
        return

    # --- Магазин ---
    if data == "open_shop":
        products = get_products()
        if not products:
            text = "🛍 *Магазин*\n\n😔 Пока товаров нет. Заходите позже!"
        else:
            text = "🛍 *Магазин*\n\nВыберите товар:"
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_shop_menu()
        )
        bot.answer_callback_query(call.id)
        return

    # --- Просмотр товара ---
    if data.startswith("view_product_"):
        pid = int(data.split("_")[2])
        product = get_product(pid)
        if not product:
            bot.answer_callback_query(call.id, "Товар уже продан", show_alert=True)
            return

        _, name, price, _ = product
        balance = get_balance(user_id)

        text = (
            f"🛍 *{name}*\n\n"
            f"💵 Цена: *{price} ₽*\n"
            f"💰 Ваш баланс: *{balance} ₽*\n\n"
        )
        if balance >= price:
            text += "✅ Достаточно средств. Можете купить!"
        else:
            text += f"⚠️ Не хватает *{price - balance} ₽*. Пополните баланс."

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("💳 Купить", callback_data=f"buy_{pid}"))
        markup.add(types.InlineKeyboardButton("⬅️ Назад в магазин", callback_data="open_shop"))

        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)
        return

    # --- Покупка ---
    if data.startswith("buy_"):
        pid = int(data.split("_")[1])
        product = get_product(pid)
        if not product:
            bot.answer_callback_query(call.id, "Товар уже продан кем-то другим", show_alert=True)
            return

        _, name, price, message_text = product
        balance = get_balance(user_id)

        if balance < price:
            bot.answer_callback_query(
                call.id,
                f"❌ Недостаточно средств. Нужно {price} ₽, у вас {balance} ₽.",
                show_alert=True
            )
            return

        # --- Списание баланса и запись покупки ---
        subtract_balance(user_id, price)
        add_purchase(user_id, pid, name, price)
        add_transaction(user_id, "purchase", -price, f"Покупка: {name}")

        # --- ⚡ УДАЛЯЕМ ТОВАР ИЗ МАГАЗИНА ---
        delete_product(pid)

        # --- Выдаём товар пользователю ---
                # --- Выдаём товар пользователю ---
        bot.send_message(
            user_id,
            f"🎁 Ваш товар «{name}»:\n\n{message_text}"
        )

        # --- Уведомление админам ---
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    f"🛒 Новая покупка!\n\n"
                    f"👤 Пользователь: {user_id}\n"
                    f"📦 Товар: {name}\n"
                    f"💵 Цена: {price} ₽"
                )
            except Exception:
                pass
        

            # --- Обновляем сообщение у пользователя ---
            new_balance = get_balance(user_id)
            bot.edit_message_text(
                f"✅ Покупка успешна!\n\n"
                f"📦 Товар: {name}\n"
                f"💵 Списано: {price} ₽\n"
                f"💰 Новый баланс: {new_balance} ₽\n\n"
                f"🎁 Товар отправлен отдельным сообщением!",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_back_menu()
            )
            bot.answer_callback_query(call.id, "✅ Покупка совершена!")
            return
            
    # --- Статистика ---
    if data == "count_accounts":
        total = get_total_users()
        text = (
            f"📊 *Статистика бота*\n\n"
            f"👥 Всего пользователей: *{total}*\n"
            f"🕐 Обновлено в реальном времени"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="count_accounts"))
        markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="main_menu"))

        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)
        return

    # --- Профиль ---
    if data == "profile":
        balance = get_balance(user_id)
        text = (
            f"👤 *Ваш профиль*\n\n"
            f"🆔 Ваш ID: `{user_id}`\n"
            f"💰 Баланс: *{balance} ₽*"
        )
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_back_menu()
        )
        bot.answer_callback_query(call.id)
        return

    # --- История транзакций ---
    if data == "history":
        transactions = get_user_transactions(user_id)
        if not transactions:
            text = "📜 *История транзакций*\n\nПока пусто."
        else:
            text = "📜 *История транзакций* (последние 20):\n\n"
            for t_type, amount, desc, created in transactions:
                if amount >= 0:
                    icon = "➕"
                    sign = "+"
                else:
                    icon = "➖"
                    sign = ""
                text += f"{icon} {sign}{amount} ₽ — {desc}\n_{created}_\n\n"

        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_back_menu()
        )
        bot.answer_callback_query(call.id)
        return

    # --- Мои покупки ---
    if data == "purchases":
        purchases = get_user_purchases(user_id)
        if not purchases:
            text = "🛒 *Мои покупки*\n\nУ вас пока нет покупок."
        else:
            text = "🛒 *Ваши покупки:*\n\n"
            for name, price, purchased in purchases:
                text += f"📦 *{name}* — {price} ₽\n_{purchased}_\n\n"

        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_back_menu()
        )
        bot.answer_callback_query(call.id)
        return

    # --- Пополнение ---
    if data == "top_up":
        bot.edit_message_text(
            get_topup_text(),
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_back_menu()
        )
        bot.register_next_step_handler(call.message, process_topup_amount)
        bot.answer_callback_query(call.id)
        return

    # --- Остальные разделы из TEXTS ---
    if data in TEXTS:
        bot.edit_message_text(
            TEXTS[data],
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_back_menu()
        )
    else:
        bot.edit_message_text(
            TEXTS["main_menu"],
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_main_menu()
        )

    bot.answer_callback_query(call.id)


# ============================================================
#   💰  ОБРАБОТКА ВВЕДЁННОЙ СУММЫ
# ============================================================

def process_topup_amount(message):
    user_id = message.from_user.id
    raw = (message.text or "").strip()

    if not raw.isdigit():
        bot.send_message(
            message.chat.id,
            "❌ Нужно ввести целое число.\nНапример: `500`",
            parse_mode='Markdown'
        )
        return

    amount_rub = int(raw)

    if amount_rub < MIN_TOPUP:
        bot.send_message(message.chat.id, f"❌ Минимум — *{MIN_TOPUP} ₽*.", parse_mode='Markdown')
        return

    if amount_rub > MAX_TOPUP:
        bot.send_message(message.chat.id, f"❌ Максимум — *{MAX_TOPUP} ₽*.", parse_mode='Markdown')
        return

    amount_usdt = round(amount_rub / USDT_TO_RUB, 2)

    try:
        invoice = crypto_create_invoice(
            amount_usdt=amount_usdt,
            description=f"Пополнение баланса на {amount_rub} ₽",
            payload=f"topup_{user_id}_{amount_rub}"
        )

        invoice_id = invoice["invoice_id"]
        pay_url = invoice["bot_invoice_url"]

        create_order(user_id, invoice_id, amount_rub)

        text = (
            f"💳 *Счёт создан!*\n\n"
            f"Сумма: *{amount_rub} ₽* (~{amount_usdt} USDT)\n"
            f"Курс: 1 USDT ≈ {round(USDT_TO_RUB, 2)} ₽\n"
            f"Счёт действителен 1 час.\n\n"
            f"Нажмите кнопку ниже для оплаты 👇"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Оплатить", url=pay_url))
        markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="main_menu"))

        bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

        threading.Thread(
            target=check_payment,
            args=(user_id, invoice_id, amount_rub),
            daemon=True
        ).start()

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при создании счёта: {e}")


# ============================================================
#   🔄  ПРОВЕРКА ОПЛАТЫ
# ============================================================

def check_payment(user_id, invoice_id, amount_rub):
    for _ in range(360):
        time.sleep(10)
        try:
            invoice = crypto_get_invoice(invoice_id)
            if not invoice:
                continue

            status = invoice.get("status")

            if status == "paid":
                if get_order_status(invoice_id) == "pending":
                    add_balance(user_id, amount_rub)
                    mark_order_paid(invoice_id)
                    add_transaction(user_id, "topup", amount_rub, "Пополнение баланса")

                    bot.send_message(
                        user_id,
                        f"✅ *Оплата получена!*\n\n"
                        f"Баланс пополнен на *{amount_rub} ₽*.\n"
                        f"Проверьте профиль!",
                        parse_mode='Markdown'
                    )

                    bot.send_message(
                        ADMIN_IDS[0],
                        f"💰 *Новая оплата!*\n\n"
                        f"Пользователь: `{user_id}`\n"
                        f"Сумма: *{amount_rub} ₽*",
                        parse_mode='Markdown'
                    )
                return

            elif status == "expired":
                return

        except Exception:
            pass


# ============================================================
#   💬  ТЕКСТОВЫЕ СООБЩЕНИЯ
# ============================================================

@bot.message_handler(content_types=['text'])
def handle_text(message):
    text = (message.text or "").strip()

    if text.startswith('/'):
        bot.send_message(
            message.chat.id,
            f"❓ Неизвестная команда: `{text}`\nНапиши /help",
            parse_mode='Markdown'
        )
        return

    bot.send_message(message.chat.id, "Не понимаю :( \nНапиши /help")


# ============================================================
#   🚀  ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("Бот запущен...")
    get_usdt_rub_rate()
    threading.Thread(target=rate_updater, daemon=True).start()
    bot.infinity_polling()
