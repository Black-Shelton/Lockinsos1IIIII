# -*- coding: utf-8 -*-
# ============================================================
#  NooB ExPeRiMeNt — бот для получения карточек (v3.0)
# ============================================================

import os
import re
import time
import random
import sqlite3
import threading
import traceback
import asyncio
from datetime import datetime, timezone, timedelta

import sys
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

MSK = timezone(timedelta(hours=3))

from aiogram import Bot as AiogramBot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardButton as AiogramInlineKeyboardButton,
    InlineKeyboardMarkup as AiogramInlineKeyboardMarkup,
    LabeledPrice as AiogramLabeledPrice,
    BufferedInputFile,
    FSInputFile,
    ReplyParameters,
)


class _InlineKeyboardButton:
    def __init__(self, text, url=None, callback_data=None, style=None):
        self.text = text
        self.url = url
        self.callback_data = callback_data
        self.style = style  # 'primary' (blue), 'success' (green), 'danger' (red)


class _InlineKeyboardMarkup:
    def __init__(self, row_width=3):
        self.row_width = row_width
        self.keyboard = []

    def add(self, *buttons):
        if not buttons:
            return self
        if len(buttons) == 1:
            self.keyboard.append(list(buttons))
        else:
            for i in range(0, len(buttons), self.row_width):
                self.keyboard.append(list(buttons[i:i + self.row_width]))
        return self

    def row(self, *buttons):
        if buttons:
            self.keyboard.append(list(buttons))
        return self

    def as_aiogram(self):
        return AiogramInlineKeyboardMarkup(
            inline_keyboard=[
                [AiogramInlineKeyboardButton(
                    text=button.text,
                    url=button.url,
                    callback_data=button.callback_data,
                    style=getattr(button, "style", None),
                ) for button in row]
                for row in self.keyboard
            ]
        )


class _LabeledPrice:
    def __init__(self, label, amount):
        self.label = label
        self.amount = amount


class _Types:
    InlineKeyboardMarkup = _InlineKeyboardMarkup
    InlineKeyboardButton = _InlineKeyboardButton
    LabeledPrice = _LabeledPrice


types = _Types()


class _SyncAiogramBot:
    """Синхронный фасад над Aiogram 3."""

    def __init__(self, token):
        self.aiogram = AiogramBot(
            token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.loop = None

    def _run(self, coroutine):
        if self.loop is None or not self.loop.is_running():
            return asyncio.run(coroutine)
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result()

    @staticmethod
    def _markup(value):
        return value.as_aiogram() if hasattr(value, "as_aiogram") else value

    @staticmethod
    def _kwargs(kwargs):
        kwargs = dict(kwargs)
        kwargs.pop("parse_mode", None)
        reply_to = kwargs.pop("reply_to_message_id", None)
        if reply_to is not None and "reply_parameters" not in kwargs:
            kwargs["reply_parameters"] = ReplyParameters(message_id=reply_to)
        return kwargs

    def get_me(self):
        return self._run(self.aiogram.get_me())

    def delete_webhook(self, drop_pending_updates=False):
        return self._run(self.aiogram.delete_webhook(drop_pending_updates=drop_pending_updates))

    def send_message(self, chat_id, text, **kwargs):
        kwargs = self._kwargs(kwargs)
        kwargs["reply_markup"] = self._markup(kwargs.get("reply_markup"))
        return self._run(self.aiogram.send_message(chat_id, text, **kwargs))

    def reply_to(self, message, text, **kwargs):
        return self.send_message(message.chat.id, text, reply_to_message_id=message.message_id, **kwargs)

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        kwargs = self._kwargs(kwargs)
        kwargs["reply_markup"] = self._markup(kwargs.get("reply_markup"))
        return self._run(self.aiogram.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs))

    def answer_callback_query(self, callback_query_id, text=None, **kwargs):
        if text is not None:
            kwargs["text"] = text
        kwargs = self._kwargs(kwargs)
        return self._run(self.aiogram.answer_callback_query(callback_query_id=callback_query_id, **kwargs))

    def answer_pre_checkout_query(self, pre_checkout_query_id, **kwargs):
        return self._run(self.aiogram.answer_pre_checkout_query(pre_checkout_query_id=pre_checkout_query_id, **kwargs))

    def send_photo(self, chat_id, photo, **kwargs):
        kwargs = self._kwargs(kwargs)
        kwargs["reply_markup"] = self._markup(kwargs.get("reply_markup"))
        return self._run(self.aiogram.send_photo(chat_id, photo, **kwargs))

    def download_photo(self, file_id, dest_path):
        return self._run(self.aiogram.download(file_id, destination=dest_path))

    def send_document(self, chat_id, document, **kwargs):
        kwargs = self._kwargs(kwargs)
        if hasattr(document, "read"):
            filename = kwargs.pop("visible_file_name", None) or getattr(document, "name", "document")
            document = BufferedInputFile(document.read(), filename=filename)
        elif isinstance(document, str):
            document = FSInputFile(document)
        kwargs["reply_markup"] = self._markup(kwargs.get("reply_markup"))
        return self._run(self.aiogram.send_document(chat_id, document, **kwargs))

    def send_invoice(self, chat_id, **kwargs):
        kwargs = dict(kwargs)
        if "invoice_payload" in kwargs:
            kwargs["payload"] = kwargs.pop("invoice_payload")
        prices = kwargs.get("prices")
        if prices:
            kwargs["prices"] = [AiogramLabeledPrice(label=p.label, amount=p.amount) for p in prices]
        return self._run(self.aiogram.send_invoice(chat_id, **kwargs))

    def promote_chat_member(self, chat_id, user_id, **kwargs):
        return self._run(self.aiogram.promote_chat_member(chat_id=chat_id, user_id=user_id, **kwargs))

    def restrict_chat_member(self, chat_id, user_id, permissions, **kwargs):
        from aiogram.types import ChatPermissions
        return self._run(self.aiogram.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions, **kwargs))

    def copy_message(self, chat_id, from_chat_id, message_id, **kwargs):
        return self._run(self.aiogram.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id, **self._kwargs(kwargs)))

    def forward_message(self, chat_id, from_chat_id, message_id, **kwargs):
        return self._run(self.aiogram.forward_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id, **self._kwargs(kwargs)))

    def delete_message(self, chat_id, message_id, **kwargs):
        return self._run(self.aiogram.delete_message(chat_id=chat_id, message_id=message_id, **self._kwargs(kwargs)))


# ========================= НАСТРОЙКИ =========================
TOKEN = "8561580446:AAF3sbzWdDv3yiQ3i30qleUDdrHrq7n9FFw"
CREATORS = [7884553468, 5679778859]
# DATA_DIR указывает на примонтированный persistent disk Render (см. render.yaml).
# Если диск не настроен (например, локальный запуск) — используется папка рядом со скриптом,
# как и раньше, ничего не ломается.
DATA_DIR = os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "noob_bot.db")

BOT_VERSION = "3.0"
BONUS_COOLDOWN = 24 * 3600
CARD_COOLDOWN = 2 * 3600
BATTLE_COOLDOWN = 3600
# Прогрессивная система уровней:
# Уровень 1 = 5 опыта, уровень 2 = 15, уровень 3 = 30 и т.д.
# Суммарный опыт до уровня N = 5 * N*(N+1) / 2
import math as _math

def level_to_points(level):
    """Суммарный опыт, нужный чтобы достичь данного уровня."""
    return 5 * level * (level + 1) // 2

def points_to_level(points):
    """Уровень по суммарному опыту."""
    if points <= 0:
        return 0
    return int((_math.sqrt(1 + 8 * points / 5) - 1) / 2)
CHAT_LINK = "https://t.me/+BaT3pOEsPiY5ZWNi"
CARD_WORD = "эксперимент"

PRIVILEGES = {
    "Игрок":                   {"card_cd": CARD_COOLDOWN,        "coin_mult": 1, "battle_cd": BATTLE_COOLDOWN},
    "NooB Premium":            {"card_cd": CARD_COOLDOWN - 1800, "coin_mult": 2, "battle_cd": BATTLE_COOLDOWN - 300},
    "Бета Тестер":             {"card_cd": 1800,                 "coin_mult": 2, "battle_cd": BATTLE_COOLDOWN - 300},
    "Продавец | Бета Тестер":  {"card_cd": 1800,                 "coin_mult": 2, "battle_cd": BATTLE_COOLDOWN - 300},
}

SHOP_ITEMS = [
    {"key": "leader", "name": "NooB Premium", "price": 3,
     "desc": "1. −30 минут к ожиданию карты\n2. −5 минут к битве карт\n3. х2 монеты с бонуса"},
]

# ========================= РЕДКОСТИ =========================
RARITY_CHANCES = [
    ("Обычная",     38.49),
    ("Необычная",   25.0),
    ("Редкая",      15.0),
    ("Эпическая",   10.0),
    ("Легендарная",  6.0),
    ("Мифическая",   3.5),
    ("Секретная",    1.0),
    ("???",          0.01),
]

RARITY_ORDER = [
    "Обычная", "Необычная", "Редкая", "Эпическая",
    "Легендарная", "Мифическая", "Секретная", "???",
]

RARITY_EMOJI = {
    "Обычная":      "⬜",
    "Необычная":    "🟩",
    "Редкая":       "🟦",
    "Эпическая":    "🟪",
    "Легендарная":  "🟨",
    "Мифическая":   "🟥",
    "Секретная":    "⬛",
    "???":          "⬛",
}

RARITY_EN = {
    "Обычная":      "Common",
    "Необычная":    "Uncommon",
    "Редкая":       "Rare",
    "Эпическая":    "Epic",
    "Легендарная":  "Legendary",
    "Мифическая":   "Mythic",
    "Секретная":    "Secret",
    "???":          "???",
}

# Монеты за карту по редкости
RARITY_COINS = {
    "Обычная":      10,
    "Необычная":    20,
    "Редкая":       40,
    "Эпическая":    80,
    "Легендарная":  160,
    "Мифическая":   320,
    "Секретная":    1000,
    "???":          5000,
}

# ========================= КАРТЫ =========================
# Формат: (название, редкость, сила, стоимость, url_фото)
CARDS = [
    ("Noob",            "Обычная",     1,   10,
     "https://www.image2url.com/r2/default/images/1791059895266-d8b74ab3-d7e5-4b2f-bd62-f3cb016fbcf1.jpg"),
    ("Dual Sword Noob", "Необычная",   5,   20,
     "https://www.image2url.com/r2/default/images/1791059900608-95e01d5f-6895-4a0a-97e0-c646e5bcdafb.jpg"),
    ("Guest",           "Необычная",   5,   20,
     "https://www.image2url.com/r2/default/images/1791134199060-2cc49b56-29a9-46a6-aac0-167e2cfa5aa6.jpg"),
    ("Large Noob",      "Редкая",      10,  40,
     "https://www.image2url.com/r2/default/images/1791060016053-de070fb9-ef4f-42c8-8041-ed1c4e6c47ec.jpg"),
    ("Guest Woman",     "Редкая",      10,  40,
     "https://www.image2url.com/r2/default/images/1791134204189-74017f66-e2ab-4a75-880b-095bb15e5658.jpg"),
    ("Grappler Noob",   "Эпическая",   20,  80,
     "https://www.image2url.com/r2/default/images/1791060019947-8744cd5d-2e6e-4f05-b8ba-0b810b71fe54.jpg"),
    ("Large Guest",     "Эпическая",   30,  80,
     "https://www.image2url.com/r2/default/images/1791134376156-6e1c3936-9a45-4a9d-80b5-2a08efc10dba.jpg"),
    ("Noob Mech",       "Легендарная", 50,  160,
     "https://www.image2url.com/r2/default/images/1791060357401-be377e3b-e9dc-451c-91dc-f94bde08d9a9.jpg"),
    ("Mech Guest",      "Легендарная", 70,  160,
     "https://www.image2url.com/r2/default/images/1791134381221-ad6aa26e-e75a-45ec-9e3e-b979ec8510e9.jpg"),
    ("Titan Noob",      "Мифическая",  100, 320,
     "https://www.image2url.com/r2/default/images/1791060361786-ca486d29-dfbe-4a97-ac8d-1ab5d7abb18a.jpg"),
    ("Titan Guest",     "Мифическая",  120, 320,
     "https://www.image2url.com/r2/default/images/1791134578454-a2b502f5-5226-4247-8890-cbb498df39e2.jpg"),
    ("Шанс",            "???",         950, 5000,
     "https://www.image2url.com/r2/default/images/1789785332160-fd33ce76-5c50-4e75-97f2-f7aaf5d080ea.jpg"),
    # Spider Crate cards
    ("Spider Noob 1.0", "Эпическая",   35,  80,
     "https://www.image2url.com/r2/default/images/1791570915796-8fa229a2-73b4-48be-8309-398dc569bef1.jpg"),
    ("Spider Noob 2.0", "Мифическая",  80,  320,
     "https://www.image2url.com/r2/default/images/1791570920392-333dc794-793e-484e-abe3-1b5523f96449.jpg"),
    ("Spider Guest",    "Легендарная", 45,  160,
     "https://www.image2url.com/r2/default/images/1791570925067-5e13c71a-7b06-4d88-818f-23fe9545816d.jpg"),
]

# ========================= КЕЙСЫ =========================
CRATES = {
    "spider": {
        "name": "Spider Crate",
        "emoji": "🕷",
        "cost": 400,
        "desc": "Пауки повсюду! Открой и узнай кто попался.",
        "cards": [
            {"card": "Spider Noob 1.0", "chance": 50.0},
            {"card": "Spider Guest",    "chance": 35.0},
            {"card": "Spider Noob 2.0", "chance": 5.0},
        ]
    }
}

# Карты из кейсов — в обычном «эксперименте» не выпадают
CRATE_CARD_NAMES = {item["card"] for cr in CRATES.values() for item in cr["cards"]}

# Опыт карты (если отличается от Силы)
CARD_EXP_OVERRIDE = {
    "Шанс":          900,
    "Guest":          5,
    "Guest Woman":   10,
    "Large Guest":   20,
    "Mech Guest":    50,
    "Titan Guest":  100,
    "Spider Noob 1.0": 35,
    "Spider Noob 2.0": 80,
    "Spider Guest":    45,
}


def get_card_exp(card_id):
    return CARD_EXP_OVERRIDE.get(CARDS[card_id][0], CARDS[card_id][2])


def get_rank(level):
    if level >= 40:
        return "🔵 Алмаз"
    elif level >= 30:
        return "⚫ Платина"
    elif level >= 20:
        return "🟡 Золото"
    elif level >= 10:
        return "⚪ Серебро"
    else:
        return "🟤 Бронза"



db_lock = threading.Lock()

# ========================= БАЗА ДАННЫХ =========================
def db():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_table(conn, name, create_sql):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    if not cur.fetchone():
        conn.execute(create_sql)
        conn.commit()

def ensure_columns(conn, table, columns):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, ddl in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            conn.commit()

def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit()

def migrate():
    conn = db()
    ensure_table(conn, "meta", "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    ensure_table(conn, "users", """
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', nickname TEXT DEFAULT 'Игрок',
            privilege TEXT DEFAULT 'Игрок', coins INTEGER DEFAULT 0, level INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0, strength INTEGER DEFAULT 0, cards_received INTEGER DEFAULT 0,
            last_bonus REAL DEFAULT 0, last_card REAL DEFAULT 0, created REAL DEFAULT 0
        )""")
    ensure_table(conn, "user_cards", """
        CREATE TABLE user_cards (
            user_id INTEGER, card_id INTEGER, count INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, card_id)
        )""")
    ensure_table(conn, "promo", """
        CREATE TABLE promo (
            code TEXT PRIMARY KEY, reward TEXT, rlimit INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created REAL DEFAULT 0
        )""")
    ensure_table(conn, "promo_used", "CREATE TABLE promo_used (code TEXT, user_id INTEGER, PRIMARY KEY (code, user_id))")
    ensure_table(conn, "chats", "CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, title TEXT DEFAULT '', username TEXT DEFAULT '', ctype TEXT DEFAULT '')")
    ensure_table(conn, "bans", "CREATE TABLE bans (user_id INTEGER PRIMARY KEY, banned_until REAL DEFAULT 0, reason TEXT DEFAULT '')")
    ensure_table(conn, "referrals", "CREATE TABLE referrals (referrer_id INTEGER, referee_id INTEGER PRIMARY KEY, coins_given INTEGER DEFAULT 0, created REAL DEFAULT 0)")
    ensure_table(conn, "card_global_counts", "CREATE TABLE card_global_counts (card_name TEXT PRIMARY KEY, total INTEGER DEFAULT 0)")
    ensure_table(conn, "custom_cards", """
        CREATE TABLE custom_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rarity TEXT,
            strength INTEGER DEFAULT 0, cost INTEGER DEFAULT 0, exp INTEGER DEFAULT 0,
            photo_ref TEXT, photo_path TEXT, created_by INTEGER DEFAULT 0, created REAL DEFAULT 0
        )""")

    ensure_columns(conn, "users", {
        "username": "TEXT DEFAULT ''", "nickname": "TEXT DEFAULT 'Игрок'",
        "privilege": "TEXT DEFAULT 'Игрок'", "coins": "INTEGER DEFAULT 0",
        "level": "INTEGER DEFAULT 0", "points": "INTEGER DEFAULT 0",
        "strength": "INTEGER DEFAULT 0", "cards_received": "INTEGER DEFAULT 0",
        "last_bonus": "REAL DEFAULT 0", "last_card": "REAL DEFAULT 0",
        "last_battle": "REAL DEFAULT 0", "created": "REAL DEFAULT 0",
    })
    ensure_columns(conn, "promo", {
        "rlimit": "INTEGER DEFAULT 0", "used": "INTEGER DEFAULT 0",
        "active": "INTEGER DEFAULT 1", "created": "REAL DEFAULT 0",
    })

    now = time.time()
    conn.execute("UPDATE users SET last_bonus=0 WHERE last_bonus > ?", (now + 600,))
    conn.execute("UPDATE users SET last_card=0 WHERE last_card > ?", (now + 600,))
    conn.commit()

    if get_meta(conn, "version") != BOT_VERSION:
        set_meta(conn, "version", BOT_VERSION)
    conn.close()

migrate()

# ========================= КАСТОМНЫЕ КАРТЫ (.создать карта) =========================
CARD_PHOTOS_DIR = os.path.join(DATA_DIR, "card_photos")
os.makedirs(CARD_PHOTOS_DIR, exist_ok=True)

RARITY_ALIASES = {
    "обычный": "Обычная", "обычная": "Обычная", "обычное": "Обычная", "common": "Обычная",
    "необычный": "Необычная", "необычная": "Необычная", "uncommon": "Необычная",
    "редкий": "Редкая", "редкая": "Редкая", "rare": "Редкая",
    "эпический": "Эпическая", "эпическая": "Эпическая", "epic": "Эпическая",
    "легендарный": "Легендарная", "легендарная": "Легендарная", "legendary": "Легендарная",
    "мифический": "Мифическая", "мифическая": "Мифическая", "mythic": "Мифическая",
    "секретный": "Секретная", "секретная": "Секретная", "secret": "Секретная",
    "???": "???",
}

def normalize_rarity(raw):
    key = (raw or "").strip().lower()
    return RARITY_ALIASES.get(key)

def parse_card_caption(text):
    text = text or ""

    def grab(label):
        m = re.search(rf"{label}\s*:\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    name = grab("Название Карты")
    rarity_raw = grab("Редкость Карты")
    cost_raw = grab("Стоимость Карты")
    strength_raw = grab("Сила Карты")
    exp_raw = grab("Опыт Карты")

    if not name:
        return None, "❌ Не указано «Название Карты»."
    rarity = normalize_rarity(rarity_raw)
    if not rarity:
        return None, ("❌ Не распознал редкость «" + esc(rarity_raw) + "».\n"
                       "Используй: обычный | необычный | редкий | эпический | Легендарный | мифический | ???")
    if not cost_raw.isdigit():
        return None, "❌ «Стоимость Карты» должна быть числом."
    if not strength_raw.isdigit():
        return None, "❌ «Сила Карты» должна быть числом."
    if find_card(name) is not None:
        return None, f"❌ Карта с именем «{esc(name)}» уже существует."

    cost = int(cost_raw)
    strength = int(strength_raw)
    exp = int(exp_raw) if exp_raw.isdigit() else strength
    return {"name": name, "rarity": rarity, "cost": cost, "strength": strength, "exp": exp}, None

def load_custom_cards():
    conn = db()
    rows = conn.execute("SELECT * FROM custom_cards ORDER BY id ASC").fetchall()
    conn.close()
    for row in rows:
        CARDS.append((row["name"], row["rarity"], row["strength"], row["cost"], row["photo_ref"]))
        if row["exp"] and row["exp"] != row["strength"]:
            CARD_EXP_OVERRIDE[row["name"]] = row["exp"]

load_custom_cards()

def save_custom_card(name, rarity, strength, cost, exp, photo_ref, photo_path, created_by):
    with db_lock:
        conn = db()
        cur = conn.execute(
            "INSERT INTO custom_cards (name, rarity, strength, cost, exp, photo_ref, photo_path, created_by, created) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, rarity, strength, cost, exp, photo_ref, photo_path, created_by, time.time()),
        )
        conn.commit()
        conn.close()
    CARDS.append((name, rarity, strength, cost, photo_ref))
    if exp != strength:
        CARD_EXP_OVERRIDE[name] = exp
    return len(CARDS) - 1

def get_user(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row

def register_user(message):
    if not message.from_user:
        return None
    if message.from_user.is_bot:
        return None
    uid = message.from_user.id
    nick = message.from_user.first_name or message.from_user.username or "Игрок"
    uname = message.from_user.username or ""
    with db_lock:
        conn = db()
        row = conn.execute("SELECT privilege FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row:
            priv = "Создатель" if uid in CREATORS else "Игрок"
            conn.execute("INSERT OR IGNORE INTO users (user_id, username, nickname, privilege, created) VALUES (?,?,?,?,?)",
                         (uid, uname, nick, priv, time.time()))
        else:
            conn.execute("UPDATE users SET username=?, nickname=? WHERE user_id=?", (uname, nick, uid))
        conn.commit()
        conn.close()
    return get_user(uid)

def ensure_user_exists(uid, nickname="Игрок"):
    with db_lock:
        conn = db()
        row = conn.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row:
            conn.execute("INSERT OR IGNORE INTO users (user_id, username, nickname, privilege, created) VALUES (?,?,?,?,?)",
                         (uid, "", nickname, "Создатель" if uid in CREATORS else "Игрок", time.time()))
            conn.commit()
        conn.close()
    return get_user(uid)

def register_chat(message):
    try:
        chat = message.chat
        title = chat.title or (message.from_user.first_name if message.from_user else "ЛС") or "Чат"
        uname = chat.username or ""
        with db_lock:
            conn = db()
            conn.execute("INSERT OR REPLACE INTO chats (chat_id, title, username, ctype) VALUES (?,?,?,?)",
                         (chat.id, str(title), uname, chat.type))
            conn.commit()
            conn.close()
    except Exception:
        pass

def upd_user(uid, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [uid]
    with db_lock:
        conn = db()
        conn.execute(f"UPDATE users SET {sets} WHERE user_id=?", vals)
        conn.commit()
        conn.close()

def add_points(uid, pts):
    u = get_user(uid)
    if not u:
        return False, 0
    new_points = u["points"] + pts
    new_level = max(u["level"], points_to_level(new_points))
    leveled = new_level > u["level"]
    upd_user(uid, points=new_points, level=new_level)
    return leveled, new_level

def add_card(uid, card_id, n=1):
    card_name = CARDS[card_id][0] if card_id < len(CARDS) else ""
    with db_lock:
        conn = db()
        row = conn.execute("SELECT count FROM user_cards WHERE user_id=? AND card_id=?", (uid, card_id)).fetchone()
        if row:
            conn.execute("UPDATE user_cards SET count=count+? WHERE user_id=? AND card_id=?", (n, uid, card_id))
        else:
            conn.execute("INSERT OR IGNORE INTO user_cards (user_id, card_id, count) VALUES (?,?,?)", (uid, card_id, n))
        conn.execute("UPDATE users SET cards_received=cards_received+? WHERE user_id=?", (n, uid))
        if card_name:
            conn.execute(
                "INSERT INTO card_global_counts (card_name, total) VALUES (?,?) "
                "ON CONFLICT(card_name) DO UPDATE SET total=total+?",
                (card_name, n, n)
            )
        conn.commit()
        conn.close()


def get_card_global_count(card_name):
    """Сколько раз эта карта выбита у всех игроков (суммируем из user_cards)."""
    card_id = find_card(card_name)
    if card_id is None:
        return 0
    conn = db()
    row = conn.execute(
        "SELECT COALESCE(SUM(count), 0) AS total FROM user_cards WHERE card_id=?", (card_id,)
    ).fetchone()
    conn.close()
    return int(row["total"]) if row else 0

def remove_card(uid, card_id, n=1):
    with db_lock:
        conn = db()
        row = conn.execute("SELECT count FROM user_cards WHERE user_id=? AND card_id=?", (uid, card_id)).fetchone()
        if not row or row["count"] < n:
            conn.close()
            return False
        if row["count"] == n:
            conn.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (uid, card_id))
        else:
            conn.execute("UPDATE user_cards SET count=count-? WHERE user_id=? AND card_id=?", (n, uid, card_id))
        conn.commit()
        conn.close()
        return True

def get_user_cards(uid):
    conn = db()
    rows = conn.execute("SELECT card_id, count FROM user_cards WHERE user_id=? ORDER BY card_id", (uid,)).fetchall()
    conn.close()
    return rows

def find_card(name):
    low = name.strip().lower()
    for i, c in enumerate(CARDS):
        if c[0].lower() == low:
            return i
    for i, c in enumerate(CARDS):
        if low in c[0].lower():
            return i
    return None

# ========================= БОТ =========================
bot = _SyncAiogramBot(TOKEN)

def safe_call(func, *args, **kwargs):
    for attempt in range(6):
        try:
            return func(*args, **kwargs)
        except (TelegramAPIError, TelegramRetryAfter) as e:
            s = str(e)
            retry_after = getattr(e, "retry_after", None)
            if retry_after is not None or "Too Many Requests" in s or "retry after" in s.lower():
                m = re.search(r"retry after (\d+)", s)
                time.sleep(int(retry_after or (m.group(1) if m else 4)) + 1)
                continue
            if "MESSAGE_NOT_MODIFIED" in s or "message is not modified" in s.lower():
                return False
            if "message can't be edited" in s or "message to edit not found" in s:
                return None
            raise
        except (ConnectionError, OSError, asyncio.TimeoutError):
            time.sleep(3)
            continue
    return None

def safe_edit(chat_id, message_id, text, reply_markup=None, fallback_new=False):
    try:
        result = safe_call(bot.edit_message_text, text, chat_id=chat_id,
                           message_id=message_id, reply_markup=reply_markup, parse_mode="HTML")
        if result is not None:
            return result
        if fallback_new:
            return safe_call(bot.send_message, chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
        return None
    except Exception:
        if fallback_new:
            try:
                return safe_call(bot.send_message, chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
            except Exception:
                pass
        return None

def guard(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            err_text = traceback.format_exc()
            traceback.print_exc()
            try:
                obj = args[0]
                if hasattr(obj, "data") and hasattr(obj, "message"):
                    sender_id = getattr(getattr(obj, "from_user", None), "id", 0)
                    chat_id = obj.message.chat.id
                    try:
                        bot.answer_callback_query(obj.id, "⚠️ Ошибка, попробуй ещё раз.")
                    except Exception:
                        pass
                    if sender_id in CREATORS:
                        bot.send_message(chat_id, f"⚠️ <b>Ошибка (debug):</b>\n<code>{esc(err_text[-1000:])}</code>")
                elif hasattr(obj, "message_id") and hasattr(obj, "chat"):
                    sender_id = getattr(getattr(obj, "from_user", None), "id", 0)
                    if sender_id in CREATORS:
                        bot.reply_to(obj, f"⚠️ <b>Ошибка (debug):</b>\n<code>{esc(err_text[-1000:])}</code>")
                    else:
                        bot.reply_to(obj, "⚠️ Произошла ошибка, попробуй ещё раз.")
            except Exception:
                pass
    wrapper.__name__ = func.__name__
    return wrapper

def fmt_time(sec):
    sec = max(0, int(sec))
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    if h:
        return f"{h}ч {m}мин"
    if m:
        return f"{m}мин {s}сек"
    return f"{s}сек"

def fmt_human(sec):
    sec = int(sec)
    h, sec = divmod(sec, 3600)
    m = sec // 60
    parts = []
    if h:
        parts.append("1 Час" if h == 1 else (f"{h} Часа" if h < 5 else f"{h} Часов"))
    if m:
        parts.append(f"{m} Мин")
    return " ".join(parts) or "0 Мин"

def fmt_chance(ch):
    return str(int(ch)) if float(ch).is_integer() else str(ch)

def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

BOT_USERNAME = ""
BOT_ID = 0

ADMIN_STATE = {}
CARD_CREATE_STATE = {}  # uid -> True, ждём фото+подпись для .создать карта
CARD_VIEW = {}
INV_PAGES = {}
INV_MSG_OWNER = {}
SHOP_MSG_OWNER = {}
TOP_MSG_OWNER = {}
MENU_MSG_OWNER = {}
TRADE_INVITES = {}
INVITE_SEQ = [0]
MENU_STATE = {}  # uid -> "promo" | "trade"
BATTLE_CHALLENGES = {}
BATTLE_SELECT = {}
BATTLE_SEQ = [0]
BOT_BATTLE_NAMES = ["NooB-Bot", "Guardian", "Shadow", "Ghost"]

# ========================= БЕЙДЖИ =========================
BADGE_USERS = {7884553468: "✅"}

def nick_badged(uid, nick):
    b = BADGE_USERS.get(uid)
    return f"{nick} {b}" if b else str(nick)

# ========================= КЛАВИАТУРЫ =========================
def kb_start():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💬 Наша Беседа", url=CHAT_LINK))
    return kb

def kb_top_menu():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("💰 Топ Монет",  callback_data="top:coins"),
        types.InlineKeyboardButton("🔋 Топ Уровня", callback_data="top:level"),
        types.InlineKeyboardButton("🌟 Топ Очков",  callback_data="top:points"),
    )
    return kb

def kb_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👤 Профиль",   callback_data=f"menu:{uid}:profile", style="primary"),
        types.InlineKeyboardButton("🎒 Инвентарь", callback_data=f"menu:{uid}:inv", style="primary"),
    )
    kb.add(
        types.InlineKeyboardButton("🛒 Магазин",   callback_data=f"menu:{uid}:shop", style="primary"),
        types.InlineKeyboardButton("📦 Кейсы",     callback_data=f"menu:{uid}:cases", style="primary"),
    )
    kb.add(
        types.InlineKeyboardButton("🎟 Промокод",  callback_data=f"menu:{uid}:promo", style="primary"),
        types.InlineKeyboardButton("🔄 Обмен",     callback_data=f"menu:{uid}:trade", style="primary"),
    )
    kb.add(
        types.InlineKeyboardButton("🎁 Бонус",  callback_data=f"menu:{uid}:bonus", style="primary"),
        types.InlineKeyboardButton("🏆 Топ",    callback_data=f"menu:{uid}:top", style="primary"),
    )
    return kb

def kb_admin_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎟 Промокоды",  callback_data="admin:promo"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin:stats"),
        types.InlineKeyboardButton("📢 Рассылка",   callback_data="admin:broadcast"),
        types.InlineKeyboardButton("🎁 Выдача",     callback_data="admin:give"),
        types.InlineKeyboardButton("🃏 Карты",      callback_data="admin:cards"),
        types.InlineKeyboardButton("🚫 Бан/Разбан", callback_data="admin:ban"),
        types.InlineKeyboardButton("⬅️ Выйти",      callback_data="back:help"),
    )
    return kb

def kb_admin_back():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu"))
    return kb

def kb_rarities():
    kb = types.InlineKeyboardMarkup(row_width=3)
    rars = [r for r in RARITY_ORDER if any(c[1] == r for c in CARDS)]
    buttons = [types.InlineKeyboardButton(r, callback_data=f"admin:cardlist:{r}") for r in rars]
    for i in range(0, len(buttons), 3):
        kb.add(*buttons[i:i+3])
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu"))
    return kb

def kb_rarities_user():
    kb = types.InlineKeyboardMarkup(row_width=3)
    rars = [r for r in RARITY_ORDER if any(c[1] == r for c in CARDS)]
    buttons = [types.InlineKeyboardButton(r, callback_data=f"user:cardlist:{r}") for r in rars]
    for i in range(0, len(buttons), 3):
        kb.add(*buttons[i:i+3])
    return kb

def kb_inventory(uid, page):
    raw = get_user_cards(uid)
    def rar_key(item):
        cid, _ = item
        rar = CARDS[cid][1] if cid < len(CARDS) else ""
        return RARITY_ORDER.index(rar) if rar in RARITY_ORDER else -1
    rows = sorted(raw, key=rar_key)
    per_page = 8
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    kb = types.InlineKeyboardMarkup(row_width=3)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"inv:{page-1}"))
    nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="inv:noop"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"inv:{page+1}"))
    kb.add(*nav)
    return kb, page, rows, per_page

def kb_shop():
    kb = types.InlineKeyboardMarkup(row_width=1)
    for it in SHOP_ITEMS:
        kb.add(types.InlineKeyboardButton(f"👑 {it['name']} — ⭐ {it['price']}", callback_data=f"shop:view:{it['key']}"))
    return kb

def kb_shop_item(key):
    kb = types.InlineKeyboardMarkup()
    it = SHOP_ITEMS_DICT[key]
    kb.add(types.InlineKeyboardButton(f"🛒 Купить за ⭐ {it['price']}", callback_data=f"shop:buy:{key}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="shop:back"))
    return kb



# ========================= БИТВА КАРТ =========================

def get_priv(u):
    return PRIVILEGES.get(u["privilege"], PRIVILEGES["Игрок"])

def battle_cd_left(u):
    cd = get_priv(u).get("battle_cd", BATTLE_COOLDOWN)
    now = time.time()
    last = u["last_battle"] if u and u["last_battle"] <= now else 0
    return max(0, cd - (now - last))

def kb_battle_mode(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🤖 Против бота",   callback_data=f"battle:mode:bot:{uid}"),
        types.InlineKeyboardButton("👥 Против игрока", callback_data=f"battle:mode:pvp:{uid}"),
    )
    return kb

def kb_battle_cards_pve(uid):
    kb = types.InlineKeyboardMarkup(row_width=1)
    seen = set()
    for cid, _ in get_user_cards(uid):
        if cid in seen or cid >= len(CARDS):
            continue
        seen.add(cid)
        c = CARDS[cid]
        kb.add(types.InlineKeyboardButton(
            f"{c[0]}  |  Сила: {c[2]}",
            callback_data=f"battle:pick:pve:{cid}",
        ))
    return kb if seen else None

def kb_battle_cards_pvp(uid, bid):
    kb = types.InlineKeyboardMarkup(row_width=1)
    seen = set()
    for cid, _ in get_user_cards(uid):
        if cid in seen or cid >= len(CARDS):
            continue
        seen.add(cid)
        c = CARDS[cid]
        kb.add(types.InlineKeyboardButton(
            f"{c[0]}  |  Сила: {c[2]}",
            callback_data=f"battle:pick:pvp:{bid}:{cid}",
        ))
    return kb if seen else None

def run_battle_pve(uid, card_id):
    u = get_user(uid)
    if not u:
        return "Ошибка профиля."
    p_card = CARDS[card_id]
    bot_cid = random.randint(0, len(CARDS) - 1)
    b_card  = CARDS[bot_cid]
    p_str, b_str = p_card[2], b_card[2]
    bot_name = random.choice(BOT_BATTLE_NAMES)

    coins_won = 0
    if p_str > b_str:
        winner = esc(u["nickname"])
        coins_won = random.randint(30, 80) * get_priv(u)["coin_mult"]
        upd_user(uid, coins=u["coins"] + coins_won)
    elif b_str > p_str:
        winner = f"Бот ({bot_name})"
    else:
        winner = None

    upd_user(uid, last_battle=time.time())

    lines = [
        "⚔️ <b>Битва карт</b>",
        f"👤 {esc(u['nickname'])}: {esc(p_card[0])}  (Сила: {p_str})",
        f"🤖 Бот ({bot_name}): {esc(b_card[0])}  (Сила: {b_str})",
        "",
    ]
    if winner is None:
        lines.append("🤝 Ничья — силы равны!")
    elif winner == esc(u["nickname"]):
        lines.append(f"🏆 Победитель: <b>{winner}</b>")
        lines.append(f"💰 Получено монет: +{coins_won}")
    else:
        lines.append(f"💀 Победитель: <b>{winner}</b>")
    return "\n".join(lines)

def finish_pvp_battle(bid):
    room = BATTLE_CHALLENGES.get(bid)
    if not room:
        return
    a_uid, b_uid = room["a"], room["b"]
    a_card = CARDS[room["a_card"]]
    b_card = CARDS[room["b_card"]]
    a_str, b_str = a_card[2], b_card[2]
    ua, ub = get_user(a_uid), get_user(b_uid)
    a_nick = esc(ua["nickname"]) if ua else str(a_uid)
    b_nick = esc(ub["nickname"]) if ub else str(b_uid)

    coins_won = 0
    if a_str > b_str:
        winner_uid, winner_nick, loser_nick = a_uid, a_nick, b_nick
    elif b_str > a_str:
        winner_uid, winner_nick, loser_nick = b_uid, b_nick, a_nick
    else:
        winner_uid, winner_nick, loser_nick = None, "", ""

    if winner_uid:
        wu = get_user(winner_uid)
        if wu:
            coins_won = random.randint(50, 120) * get_priv(wu)["coin_mult"]
            upd_user(winner_uid, coins=wu["coins"] + coins_won)

    upd_user(a_uid, last_battle=time.time())
    upd_user(b_uid, last_battle=time.time())

    lines = [
        "⚔️ <b>Битва карт</b>",
        f"👤 {a_nick}: {esc(a_card[0])}  (Сила: {a_str})",
        f"👤 {b_nick}: {esc(b_card[0])}  (Сила: {b_str})",
        "",
    ]
    if winner_uid:
        lines.append(f"🏆 Победитель: <b>{winner_nick}</b>")
        lines.append(f"💰 Монеты: +{coins_won}")
    else:
        lines.append("🤝 Ничья — силы равны!")

    txt = "\n".join(lines)
    safe_call(bot.send_message, room.get("a_chat", a_uid), txt)
    safe_call(bot.send_message, room.get("b_chat", b_uid), txt)
    room["phase"] = "done"
    BATTLE_CHALLENGES.pop(bid, None)

# ========================= ТЕКСТЫ =========================
def txt_start(nick):
    return (f"🤖 Йоу, {esc(nick)}, ты в <b>NooB ExPeRiMeNt</b>!\n\n"
            f"Заходи, располагайся. Тут просто куча всего, чтобы убить время. "
            f"Карточки, приколы, команды — выбирай, что зайдет. 🃏\n\n"
            f"🔍 Пиши Помощь, там всё основное")

def txt_help():
    return ("📋 <b>Список Всех Команд:</b>\n"
            "════════════════════════════\n"
            "/start — Запуск Бота.\n"
            "Помощь — Все Команды.\n"
            "Меню — Главное Меню.\n"
            "Профиль — Профиль.\n"
            "Бонус (каждые 24 часа) — Ежедневный Бонус.\n"
            "Топ / Топс / Топн / Топг — Топы (💰 Монеты / 🔋 Уровни / 🌟 Очки).\n"
            "Магазин — Донат-Магазин привилегий.\n"
            "Инвентарь / Инв / Инве — Инвентарь С Картами.\n"
            "Кейсы — Открыть кейс.\n"
            "Индекс — Список всех карт (только в ЛС).\n"
            "🎟 Промо [код] — Активировать Промокод.\n"
            "🔄 Обмен [@username/ID] — Предложить обмен игроку.\n"
            "🔗 Реферал — твоя реферальная ссылка и статистика.\n"
            "🃏 Напиши «эксперимент» — получить карточку (раз в 2 часа).\n"
            "⚔️ Битва — битва карт (vs бот / vs игрок).\n"
            )

def txt_profile(u):
    rank = get_rank(u["level"])
    return (f"{nick_badged(u['user_id'], esc(u['nickname']))}, Ваш Профиль:\n"
            "════════════════════════════\n"
            f"📱 Ник: {nick_badged(u['user_id'], esc(u['nickname']))}\n"
            f"🪪 ID: {u['user_id']}\n"
            f"👑 Привилегия: {esc(u['privilege'])}\n"
            f"🏅 Ранг: {rank}\n"
            f"💰 Монеты: {u['coins']}$\n"
            f"🔋 Уровень: {u['level']}\n"
            f"🌟 Очки: {u['points']}\n"
            f"🎲 Всего Получено Карт: {u['cards_received']}")

def txt_shop():
    return ("🎖 <b>NooB Premium</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👑 <b>Привилегии</b> — за Звёзды Telegram ⭐\n\n"
            "Привилегия даёт бонусы к картам, монетам и многому другому.\n"
            "Выбери привилегию 👇")

SHOP_ITEMS_DICT = {it["key"]: it for it in SHOP_ITEMS}

def txt_admin_menu():
    return (
        "🛠 <b>Меню Нуб — Панель Разработчика</b>\n"
        "════════════════════════════\n\n"
        "🚫 <b>БАН / РАЗБАН</b>\n"
        "▫️ <code>.бан (время)</code> — бан (ответом, причина след. строкой)\n"
        "   Алиас: <code>Swoon (время)</code>\n"
        "   Время: <b>30сек</b> · <b>10мин</b> · <b>2ч</b> · <b>1д</b>\n"
        "▫️ <code>.разбан</code> / <code>.unban</code> — разбан (ответом)\n\n"
        "🎁 <b>ВЫДАЧА</b> (ответом на сообщение)\n"
        "▫️ <code>проф</code> — профиль игрока\n"
        "▫️ <code>вд карта [имя]</code>\n"
        "▫️ <code>вд монеты/очки/уровни/сила [сумма]</code>\n"
        "▫️ <code>вд привилегия [название]</code> (без названия — снять)\n"
        "▫️ <code>вд ппб</code> — выдать Продавец | Бета Тестер\n"
        "▫️ <code>забрать монеты [сумма]</code> (ответом или @user)\n"
        "▫️ <code>ресет</code> — полный сброс игрока\n\n"
        "🎟 <b>ПРОМОКОДЫ</b>\n"
        "▫️ <code>промо создать [код] [награда] [лимит]</code>\n"
        "▫️ <code>промо удалить [код]</code>\n"
        "▫️ <code>промо ред [код] награда/лимит/статус ...</code>\n"
        "▫️ <code>промо список</code> / <code>промо инфо [код]</code>\n\n"
        "📢 <b>РАССЫЛКА</b>\n"
        "▫️ <code>рассылка общий</code> — во все чаты\n"
        "▫️ <code>рассылка @чат/ID</code> — в конкретный чат\n"
        "▫️ <code>рассылка список</code> — список групп (ЛС)\n"
        "▫️ <code>/b [текст]</code> — быстрая рассылка текстом\n\n"
        "🃏 <b>КАРТЫ</b>\n"
        "▫️ <code>карты список</code> — карты по редкости\n"
        "▫️ <code>.создать карта</code> — создать новую карту (только главный создатель)\n\n"
        "📊 <b>ПРОЧЕЕ</b>\n"
        "▫️ <code>стата</code> — статистика бота\n"
        "▫️ <code>$ database odev true</code> — скачать БД\n"
        "▫️ <code>!снос бота</code> — выключить бота\n"
    )

def txt_admin_promo():
    avail_privs = [p for p in PRIVILEGES if p != "Игрок"]
    return ("🎟 <b>ПРОМОКОДЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "▫️ промо создать [код] [награда] [лимит]\n"
            f"   награда: монеты 5000 | сила 50 | уровень 2 | карты (название) | очки 2 | донат [привилегия]\n"
            f"   Доступные привилегии: {', '.join(avail_privs)}\n"
            "▫️ промо удалить [код]\n"
            "▫️ промо ред [код] награда [новая награда]\n"
            "▫️ промо ред [код] лимит [число]\n"
            "▫️ промо ред [код] статус вкл/выкл\n"
            "▫️ промо список / промо инфо [код]\n\n"
            "Игроки активируют командой «промо [код]».")

def txt_admin_broadcast():
    return ("📢 <b>РАССЫЛКА</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "▫️ рассылка @чат/ссылка/ID — в одну группу\n"
            "▫️ рассылка общий — во все чаты\n"
            "▫️ рассылка список — список групп (только в ЛС)\n\n"
            "Следующим сообщением скинь контент (текст/фото/GIF/стикер/видео).")

def txt_admin_give():
    return ("🎁 <b>ВЫДАЧА</b> (ответом на сообщение игрока)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "▫️ проф — профиль игрока\n"
            "▫️ вд карта [имя]\n"
            "▫️ вд монеты/очки/уровни/сила [сумма]\n"
            "▫️ вд привилегия [название] (без названия — снять)\n\n"
            "👑 NooB Premium:\n"
            "1. −30 минут к ожиданию карты\n"
            "2. −5 минут к битве карт\n"
            "3. х2 деньги")

def txt_admin_ban():
    return (
        "🚫 <b>БАН / РАЗБАН</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Бан</b> (ответом на сообщение игрока):\n"
        "▫️ <code>.бан (время)</code>\n"
        "   Причина (необязательно — след. строкой)\n\n"
        "▫️ Алиас: <code>Swoon (время)</code>\n\n"
        "Примеры времени:\n"
        "  <code>30сек</code>  <code>10мин</code>  <code>2ч</code>  <code>1д</code>\n\n"
        "<b>Разбан</b> (ответом на сообщение игрока):\n"
        "▫️ <code>.разбан</code>\n"
        "▫️ Алиас: <code>.unban</code>"
    )

# ========================= КАРТОЧКИ =========================
def pick_card_id(uid=None):
    chances = list(RARITY_CHANCES)
    GOOD_RARS = {"Легендарная", "Мифическая", "Секретная", "???"}
    NERF_RARS = {"Обычная", "Необычная", "Редкая"}

    luck_pts = 0.0
    is_creator = False

    if uid is not None:
        u = get_user(uid)
        if u:
            if uid in CREATORS:
                is_creator = True
            if u["privilege"] == "NooB Premium":
                luck_pts += 40.0
            if u["privilege"] in ("Бета Тестер", "Продавец | Бета Тестер"):
                luck_pts += 35.0

    if is_creator:
        luck_pts += 10000.0

    if luck_pts > 0:
        good_total = sum(ch for r, ch in chances if r in GOOD_RARS)
        nerf_total = sum(ch for r, ch in chances if r in NERF_RARS)
        actual_pts = min(luck_pts, max(0.0, nerf_total - len(NERF_RARS) * 0.1))
        boosted = []
        for rar, ch in chances:
            if rar in GOOD_RARS and good_total > 0:
                ch += actual_pts * (ch / good_total)
            elif rar in NERF_RARS and nerf_total > 0:
                ch = max(0.1, ch - actual_pts * (ch / nerf_total))
            boosted.append((rar, ch))
        chances = boosted

    r = random.uniform(0, sum(ch for _, ch in chances))
    acc = 0.0
    for rar, ch in chances:
        acc += ch
        if r < acc:
            pool = [i for i, c in enumerate(CARDS) if c[1] == rar and c[0] not in CRATE_CARD_NAMES]
            if pool:
                return random.choice(pool)

    return random.choice([i for i, c in enumerate(CARDS) if c[0] not in CRATE_CARD_NAMES])


def card_drop_text(u, card, count, cooldown):
    name, rar, strength, cost, url = card
    rar_en = RARITY_EN.get(rar, rar)
    card_id = find_card(name)
    exp = get_card_exp(card_id) if card_id is not None else strength
    global_cnt = get_card_global_count(name)
    body = (f"👤 {esc(u['nickname'])}\n"
            f"🃏 Получена Новая Карта {esc(name)}\n\n"
            f"♈️ Редкость: {rar_en}.\n"
            f"💰 Стоимость: {cost}.\n"
            f"💪 Сила: {strength}.\n"
            f"🔋 Опыт: {exp}.\n"
            f"🌐 Всего выбито: {global_cnt}\n\n"
            f"🎁 Следущая Карта Через 2 Часа.")
    return f"<b>{body}</b>", url


def give_card(uid, card_id):
    add_card(uid, card_id)
    exp = get_card_exp(card_id)
    leveled, new_level = add_points(uid, exp)
    # Прибавляем силу карты к профилю
    u = get_user(uid)
    if u:
        upd_user(uid, strength=u["strength"] + CARDS[card_id][2])
    return leveled, new_level


# ========================= ПРОМОКОДЫ =========================
def valid_reward(rw):
    parts = rw.split()
    if not parts:
        return False
    t = parts[0].lower()
    if t in ("монеты", "очки", "сила", "уровни", "уровень"):
        return len(parts) == 2 and parts[1].isdigit()
    if t in ("карта", "карты"):
        return len(parts) >= 2 and find_card(" ".join(parts[1:])) is not None
    if t == "донат":
        priv_name_raw = " ".join(parts[1:]).strip()
        canon = next((p for p in PRIVILEGES if p.lower() == priv_name_raw.lower()), None)
        return canon is not None and canon != "Игрок"
    return False

def apply_reward(uid, rw):
    parts = rw.split()
    t = parts[0].lower()
    if t in ("монеты", "очки", "сила", "уровни", "уровень"):
        val = int(parts[1])
        col = {"монеты": "coins", "очки": "points", "сила": "strength",
               "уровни": "level", "уровень": "level"}[t]
        u = get_user(uid)
        new_val = u[col] + val
        fields = {col: new_val}
        leveled = False
        if t == "очки":
            new_level = max(u["level"], points_to_level(new_val))
            leveled = new_level > u["level"]
            fields["level"] = new_level
        upd_user(uid, **fields)
        names = {"монеты": "💰 Монеты", "очки": "🌟 Очки", "сила": "💪 Сила",
                 "уровни": "🔋 Уровни", "уровень": "🔋 Уровни"}
        msg = f"🎟 Активировано: {names[t]} +{val}!"
        if leveled:
            msg += f"\n🔋 Новый уровень: {fields['level']}!"
        return msg
    if t in ("карта", "карты"):
        card_id = find_card(" ".join(parts[1:]))
        if card_id is None:
            return "⚠️ Карта не найдена."
        leveled, new_level = give_card(uid, card_id)
        u = get_user(uid)
        cnt = 0
        for cid, c in get_user_cards(uid):
            if cid == card_id:
                cnt = c
        text, url = card_drop_text(u, CARDS[card_id], cnt, get_priv(u)["card_cd"])
        return ("CARD", text, url)
    if t == "донат":
        priv_name_raw = " ".join(parts[1:]).strip()
        priv_name = next((p for p in PRIVILEGES if p.lower() == priv_name_raw.lower()), None)
        if priv_name is None or priv_name == "Игрок":
            return "⚠️ Привилегия не найдена."
        upd_user(uid, privilege=priv_name)
        priv_info = PRIVILEGES.get(priv_name, {})
        cd_min = priv_info.get("card_cd", CARD_COOLDOWN) // 60
        coin_mult = priv_info.get("coin_mult", 1)
        return (f"👑 Активирована привилегия: <b>{esc(priv_name)}</b>!\n"
                f"⏱ Кулдаун карты: <b>{cd_min} мин</b>\n"
                f"💰 Бонус монет: <b>x{coin_mult}</b>")
    return "⚠️ Неизвестная награда."

# ========================= БАН =========================
def parse_ban_duration(arg):
    arg = arg.strip().lower()
    m = re.fullmatch(r"(\d+)\s*(сек|секунд[а-я]*|мин|минут[а-я]*|час[а-я]*|ч|д|дн[а-я]*|день|дней)", arg)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("сек") or unit.startswith("секунд"):
        return n
    if unit.startswith("мин") or unit.startswith("минут"):
        return n * 60
    if unit.startswith("час") or unit == "ч":
        return n * 3600
    if unit.startswith("д") or unit.startswith("дн") or unit in ("день", "дней"):
        return n * 86400
    return None

def ban_user(uid, seconds, reason=""):
    until = time.time() + seconds
    with db_lock:
        conn = db()
        conn.execute("INSERT OR REPLACE INTO bans (user_id, banned_until, reason) VALUES (?,?,?)", (uid, until, reason))
        conn.commit()
        conn.close()
    return until

def unban_user(uid):
    with db_lock:
        conn = db()
        conn.execute("DELETE FROM bans WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()

def get_ban(uid):
    conn = db()
    row = conn.execute("SELECT * FROM bans WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    if not row:
        return None
    if row["banned_until"] <= time.time():
        unban_user(uid)
        return None
    return row

def fmt_until(ts):
    return datetime.fromtimestamp(ts, tz=MSK).strftime("%H:%M %d.%m.%Y")

# ========================= РЕФЕРАЛЫ =========================
def get_ref_count(uid):
    conn = db()
    row = conn.execute("SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id=?", (uid,)).fetchone()
    conn.close()
    return row["cnt"] if row else 0

def ref_next_reward(ref_count):
    return (ref_count + 1) * 10

def process_referral(referrer_id, referee_id):
    if referrer_id == referee_id:
        return 0, 0
    conn = db()
    existing = conn.execute("SELECT 1 FROM referrals WHERE referee_id=?", (referee_id,)).fetchone()
    conn.close()
    if existing:
        return 0, 0
    with db_lock:
        conn = db()
        existing = conn.execute("SELECT 1 FROM referrals WHERE referee_id=?", (referee_id,)).fetchone()
        if existing:
            conn.close()
            return 0, 0
        conn.execute("INSERT OR IGNORE INTO referrals (referrer_id, referee_id, coins_given, created) VALUES (?,?,?,?)",
                     (referrer_id, referee_id, 0, time.time()))
        conn.commit()
        conn.close()
    new_count = get_ref_count(referrer_id)
    coins = new_count * 10
    with db_lock:
        conn = db()
        conn.execute("UPDATE referrals SET coins_given=? WHERE referee_id=?", (coins, referee_id))
        conn.commit()
        conn.close()
    u = get_user(referrer_id)
    if u:
        upd_user(referrer_id, coins=u["coins"] + coins)
    return coins, new_count

def ref_link(uid):
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    return "(запусти бота чтобы получить ссылку)"

def txt_ref_profile(uid):
    rc = get_ref_count(uid)
    next_coins = ref_next_reward(rc)
    conn = db()
    total_earned = conn.execute(
        "SELECT COALESCE(SUM(coins_given),0) AS s FROM referrals WHERE referrer_id=?", (uid,)
    ).fetchone()["s"]
    conn.close()
    return (f"🔗 <b>Реферальная Система</b>\n"
            "════════════════════════════\n"
            f"🔢 Уровень ссылки: <b>{rc}</b>\n"
            f"👥 Приглашено игроков: <b>{rc}</b>\n"
            f"💰 Всего заработано: <b>{total_earned} монет</b>\n"
            f"🎁 За следующего: <b>{next_coins} монет</b>\n\n"
            f"🔗 Твоя ссылка:\n<code>{ref_link(uid)}</code>\n\n"
            f"<i>Каждый новый игрок по ссылке даёт тебе монеты.\n"
            f"Уровень растёт — награда растёт: уровень × 10 монет.</i>")

def promo_info(code):
    conn = db()
    row = conn.execute("SELECT * FROM promo WHERE code=?", (code.upper(),)).fetchone()
    conn.close()
    return row

# ========================= ВИКТОРИНА =========================






# ========================= РАССЫЛКА =========================
def parse_chat_arg(arg):
    arg = arg.strip()
    if re.fullmatch(r"-?\d+", arg):
        return int(arg)
    m = re.search(r"t\.me/(\+?[\w\d_]+)", arg)
    if m:
        name = m.group(1)
        return "@" + name if not name.startswith("+") else "https://t.me/" + name
    if arg.startswith("@"):
        return arg
    if arg.startswith("https://t.me/"):
        return arg
    return None

def get_all_chats():
    conn = db()
    rows = conn.execute("SELECT chat_id, title, username, ctype FROM chats ORDER BY ctype, title").fetchall()
    conn.close()
    return rows

def do_broadcast(message, target):
    if target == "all":
        conn = db()
        chat_ids = [r[0] for r in conn.execute("SELECT chat_id FROM chats").fetchall()]
        conn.close()
        ids = list(dict.fromkeys(chat_ids))
    else:
        ids = [target]
    ok, fail = 0, 0
    src_chat = message.chat.id
    src_mid = message.message_id
    for cid in ids:
        sent = False
        try:
            result = safe_call(bot.copy_message, cid, src_chat, src_mid)
            if result:
                ok += 1
                sent = True
        except Exception:
            pass
        if not sent:
            try:
                result = safe_call(bot.forward_message, cid, src_chat, src_mid)
                if result:
                    ok += 1
                    sent = True
            except Exception:
                pass
        if not sent:
            fail += 1
        time.sleep(0.40)
    return ok, fail

def do_broadcast_text(text):
    conn = db()
    chat_ids = [r[0] for r in conn.execute("SELECT chat_id FROM chats").fetchall()]
    user_ids = [r[0] for r in conn.execute("SELECT user_id FROM users WHERE user_id > 0").fetchall()]
    conn.close()
    all_ids = list(dict.fromkeys(chat_ids + user_ids))
    ok, fail = 0, 0
    for cid in all_ids:
        try:
            safe_call(bot.send_message, cid, text)
            ok += 1
        except Exception:
            fail += 1
        time.sleep(0.40)
    return ok, fail

# ========================= ОБМЕН =========================
TRADE_SETUP = {}
TRADE_STATE = {}
TRADE_ROOMS = {}
ROOM_SEQ = [0]

def trade_other(room, uid):
    return room["b"] if room["a"] == uid else room["a"]

def card_count(uid, card_id):
    for cid, c in get_user_cards(uid):
        if cid == card_id:
            return c
    return 0

def fmt_offer_short(offer):
    parts = []
    if offer["coins"] > 0:
        parts.append(f"💰 {offer['coins']} монет")
    for cid, n in sorted(offer["cards"].items()):
        parts.append(f"🃏 {esc(CARDS[cid][0])} x{n}")
    return " + ".join(parts) if parts else "—"

def trade_reset_ready(room, uid):
    other = trade_other(room, uid)
    room["ready"][uid] = False
    room["ready"][other] = False
    room["confirm"][uid] = False
    room["confirm"][other] = False
    room["phase"] = "build"

def trade_room_text(room, uid):
    tid = room["tid"]
    other = trade_other(room, uid)
    uo = get_user(other)
    oname = nick_badged(other, esc(uo["nickname"])) if uo else str(other)
    banner = ""
    if room["phase"] == "confirm":
        banner = "⚠️ <b>Оба готовы!</b> Проверь предметы и подтверди обмен.\n\n"
    my_r = room["ready"].get(uid)
    op_r = room["ready"].get(other)
    return (f"{banner}🔄 <b>Обмен #{tid}</b> с {oname}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🎁 Ты отдаёшь: <b>{fmt_offer_short(room['offers'][uid])}</b>\n"
            f"📥 Ты получишь: <b>{fmt_offer_short(room['offers'][other])}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{'✅' if my_r else '⏳'} Ты: <b>{'готов' if my_r else 'не готов'}</b>   "
            f"{'✅' if op_r else '⏳'} {oname}: <b>{'готов' if op_r else 'не готов'}</b>")

def trade_kb_build(tid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("💰 Добавить монеты", callback_data=f"trade2:coins:{tid}"),
           types.InlineKeyboardButton("🃏 Добавить карту", callback_data=f"trade2:cards:{tid}"))
    kb.row(types.InlineKeyboardButton("🗑 Очистить вклад", callback_data=f"trade2:clear:{tid}"))
    kb.row(types.InlineKeyboardButton("✅ Готов", callback_data=f"trade2:ready:{tid}"),
           types.InlineKeyboardButton("❌ Отменить", callback_data=f"trade2:cancel:{tid}"))
    return kb

def trade_kb_confirm(tid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"trade2:confirm:{tid}"),
           types.InlineKeyboardButton("✏️ Изменить", callback_data=f"trade2:edit:{tid}"))
    kb.row(types.InlineKeyboardButton("❌ Отменить", callback_data=f"trade2:cancel:{tid}"))
    return kb

def trade_kb_cards(tid, uid):
    kb = types.InlineKeyboardMarkup(row_width=1)
    owned = dict(get_user_cards(uid))
    used = TRADE_ROOMS[tid]["offers"][uid]["cards"]
    added = 0
    for cid in sorted(owned):
        left = owned[cid] - used.get(cid, 0)
        if left <= 0:
            continue
        added += 1
        kb.add(types.InlineKeyboardButton(f"🃏 {CARDS[cid][0]} (доступно: {left})",
                                          callback_data=f"trade2:addcard:{tid}:{cid}"))
    if not added:
        kb.add(types.InlineKeyboardButton("— все карты уже добавлены —", callback_data="trade2:noop"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"trade2:back:{tid}"))
    return kb

def trade_push(room):
    for puid, mid in list(room["msgs"].items()):
        kb = trade_kb_confirm(room["tid"]) if room["phase"] == "confirm" else trade_kb_build(room["tid"])
        trade_set_message(room, puid, trade_room_text(room, puid), kb, source_mid=mid)

def trade_set_message(room, uid, text, reply_markup, source_mid=None):
    chat_id = room["chats"].get(uid, uid)
    message_id = source_mid if source_mid is not None else room["msgs"].get(uid)
    if message_id is None:
        return None
    result = safe_edit(chat_id, message_id, text, reply_markup=reply_markup, fallback_new=True)
    if result is not None and result is not False:
        new_mid = getattr(result, "message_id", None)
        if new_mid:
            room["msgs"][uid] = new_mid
            room["chats"][uid] = getattr(getattr(result, "chat", None), "id", chat_id)
    return result

def trade_finish_msgs(room, ok, err=""):
    tid = room["tid"]
    for puid, mid in list(room["msgs"].items()):
        other = trade_other(room, puid)
        if ok:
            txt = (f"✅ <b>Обмен #{tid} завершён!</b>\n"
                   "━━━━━━━━━━━━━━━━━━━━\n"
                   f"📤 Ты отдал: <b>{fmt_offer_short(room['offers'][puid])}</b>\n"
                   f"📥 Ты получил: <b>{fmt_offer_short(room['offers'][other])}</b>")
        else:
            txt = (f"⚠️ <b>Обмен #{tid} не состоялся.</b>\n{esc(err)}\n"
                   f"Предметы возвращены — обмен сброшен, можно продолжать.")
        safe_edit(room["chats"][puid], mid, txt, reply_markup=None, fallback_new=True)

def find_user_by_ref(ref):
    ref = ref.strip().lstrip("@")
    conn = db()
    if ref.isdigit():
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (int(ref),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (ref,)).fetchone()
    conn.close()
    return row

def user_in_trade(uid):
    for r in TRADE_ROOMS.values():
        if uid in (r["a"], r["b"]) and r["phase"] != "done":
            return True
    return False

def start_trade_room(a, b):
    ROOM_SEQ[0] += 1
    tid = ROOM_SEQ[0]
    room = {"tid": tid, "a": a, "b": b,
            "offers": {a: {"coins": 0, "cards": {}}, b: {"coins": 0, "cards": {}}},
            "ready": {a: False, b: False}, "confirm": {a: False, b: False},
            "msgs": {}, "chats": {}, "phase": "build",
            "expires": time.time() + 300}
    TRADE_ROOMS[tid] = room
    ua, ub = get_user(a), get_user(b)
    aname = esc(ua["nickname"]) if ua else str(a)
    bname = esc(ub["nickname"]) if ub else str(b)
    try:
        ma = safe_call(bot.send_message, a,
                       f"🔄 <b>Обмен создан!</b> С кем: {bname}.\n"
                       f"Добавь свои предметы кнопками ниже 👇\n\n" + trade_room_text(room, a),
                       reply_markup=trade_kb_build(tid))
        if not ma:
            raise RuntimeError("no dm A")
        room["msgs"][a] = ma.message_id
        room["chats"][a] = ma.chat.id
        mb = safe_call(bot.send_message, b,
                       f"🔄 <b>{aname}</b> предлагает тебе обмен!\n"
                       f"Добавь свои предметы кнопками ниже 👇\n\n" + trade_room_text(room, b),
                       reply_markup=trade_kb_build(tid))
        if not mb:
            raise RuntimeError("no dm B")
        room["msgs"][b] = mb.message_id
        room["chats"][b] = mb.chat.id
    except Exception:
        TRADE_ROOMS.pop(tid, None)
        safe_call(bot.send_message, a,
                  "❌ Не удалось написать игроку в ЛС. Пусть он сначала запустит бота (/start).")
        return None
    return tid

def execute_trade_room(tid):
    room = TRADE_ROOMS.get(tid)
    if not room:
        return False, "Обмен не найден."
    a, b = room["a"], room["b"]
    ua, ub = get_user(a), get_user(b)
    if not ua or not ub:
        return False, "Один из игроков не найден."
    oa, ob = room["offers"][a], room["offers"][b]
    if ua["coins"] < oa["coins"]:
        return False, f"У {ua['nickname']} не хватает монет."
    if ub["coins"] < ob["coins"]:
        return False, f"У {ub['nickname']} не хватает монет."
    for cid, n in oa["cards"].items():
        if card_count(a, cid) < n:
            return False, f"У {ua['nickname']} не хватает карты «{CARDS[cid][0]}»."
    for cid, n in ob["cards"].items():
        if card_count(b, cid) < n:
            return False, f"У {ub['nickname']} не хватает карты «{CARDS[cid][0]}»."
    upd_user(a, coins=ua["coins"] - oa["coins"] + ob["coins"])
    upd_user(b, coins=ub["coins"] - ob["coins"] + oa["coins"])
    for cid, n in oa["cards"].items():
        remove_card(a, cid, n)
        add_card(b, cid, n)
    for cid, n in ob["cards"].items():
        remove_card(b, cid, n)
        add_card(a, cid, n)
    return True, "ok"

def cleanup_trades():
    now = time.time()
    for tid, room in list(TRADE_ROOMS.items()):
        if room["phase"] != "done" and room.get("expires", 0) < now:
            TRADE_ROOMS.pop(tid, None)
            for puid, mid in list(room["msgs"].items()):
                safe_edit(room["chats"].get(puid, puid), mid,
                          f"🔄 <b>Обмен #{tid}</b>\n\n⏳ Обмен истёк.",
                          reply_markup=None, fallback_new=True)
    for store in (TRADE_SETUP, TRADE_STATE):
        for puid, st in list(store.items()):
            if st.get("expires", 0) < now:
                store.pop(puid, None)
    for iid, inv in list(TRADE_INVITES.items()):
        if inv.get("expires", 0) < now:
            TRADE_INVITES.pop(iid, None)

# ========================= НОВЫЙ ОБМЕН (invite-based) =========================
def new_trade_room_text(room, uid):
    other = trade_other(room, uid)
    uo = get_user(other)
    oname = nick_badged(other, esc(uo["nickname"])) if uo else str(other)
    my_offer = room["offers"][uid]
    op_offer = room["offers"][other]
    my_txt = fmt_offer_short(my_offer) if (my_offer["coins"] > 0 or my_offer["cards"]) else "Пусто"
    op_txt = fmt_offer_short(op_offer) if (op_offer["coins"] > 0 or op_offer["cards"]) else "Пусто"
    ready  = room.get("ready", {})
    my_r   = ready.get(uid, False)
    op_r   = ready.get(other, False)
    if my_r and not op_r:
        status = f"\n\n⏳ Ожидаем подтверждения от {oname}..."
    elif not my_r and op_r:
        status = f"\n\n⏳ {oname} уже готов — нажми Готов!"
    else:
        status = ""
    return (f"🔄 <b>Обмен с {oname}</b>\n\n"
            f"Вы Отдаёте:\n<b>{my_txt}</b>\n\n"
            f"Вы Получаете от игрока {oname}:\n<b>{op_txt}</b>{status}")

def new_trade_kb(tid, uid=None, room=None):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 Добавить Монеты", callback_data=f"trade3:coins:{tid}"),
        types.InlineKeyboardButton("🎴 Добавить Карты",  callback_data=f"trade3:cards:{tid}"),
    )
    already_ready = uid and room and room.get("ready", {}).get(uid, False)
    ready_lbl = "⏳ Ожидаем второго..." if already_ready else "✅ Готов"
    kb.add(
        types.InlineKeyboardButton(ready_lbl,    callback_data=f"trade3:accept:{tid}"),
        types.InlineKeyboardButton("❌ Отменить", callback_data=f"trade3:cancel:{tid}"),
    )
    return kb

def new_trade_kb_cards(tid, uid):
    kb = types.InlineKeyboardMarkup(row_width=1)
    owned = dict(get_user_cards(uid))
    room  = TRADE_ROOMS.get(tid)
    used  = room["offers"][uid]["cards"] if room else {}
    added = 0
    for cid in sorted(owned):
        if cid >= len(CARDS):
            continue
        left = owned[cid] - used.get(cid, 0)
        if left <= 0:
            continue
        added += 1
        c = CARDS[cid]
        kb.add(types.InlineKeyboardButton(
            f"🃏 {c[0]} [{RARITY_EN.get(c[1], c[1])}] (доступно: {left})",
            callback_data=f"trade3:addcard:{tid}:{cid}",
        ))
    if not added:
        kb.add(types.InlineKeyboardButton("— нет карт для обмена —", callback_data="trade3:noop"))
    kb.row(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"trade3:back:{tid}"))
    return kb

def new_trade_push(room):
    tid = room["tid"]
    for puid, mid in list(room["msgs"].items()):
        chat_id = room["chats"].get(puid, puid)
        safe_edit(chat_id, mid, new_trade_room_text(room, puid),
                  reply_markup=new_trade_kb(tid, puid, room), fallback_new=True)

def send_trade_invite(from_uid, to_uid, from_chat_id=None):
    fu = get_user(from_uid)
    fname = nick_badged(from_uid, esc(fu["nickname"])) if fu else str(from_uid)
    INVITE_SEQ[0] += 1
    iid = INVITE_SEQ[0]
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Принять",   callback_data=f"tinvite:accept:{iid}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"tinvite:decline:{iid}"),
    )
    msg = safe_call(bot.send_message, to_uid,
                    f"🔄 Игрок <b>{fname}</b> кинул вам обмен.",
                    reply_markup=kb)
    if not msg:
        return None
    TRADE_INVITES[iid] = {
        "a": from_uid, "b": to_uid,
        "a_chat": from_chat_id or from_uid,
        "b_msg": msg.message_id,
        "expires": time.time() + 86400 * 7,
    }
    return iid

def open_new_trade_room(a, b):
    ROOM_SEQ[0] += 1
    tid = ROOM_SEQ[0]
    room = {
        "tid": tid, "a": a, "b": b,
        "offers": {a: {"coins": 0, "cards": {}}, b: {"coins": 0, "cards": {}}},
        "msgs": {}, "chats": {},
        "phase": "build",
        "ready": {a: False, b: False},
        "expires": time.time() + 86400 * 30,
    }
    TRADE_ROOMS[tid] = room
    ua, ub = get_user(a), get_user(b)
    aname = nick_badged(a, esc(ua["nickname"])) if ua else str(a)
    bname = nick_badged(b, esc(ub["nickname"])) if ub else str(b)
    try:
        ma = safe_call(bot.send_message, a,
                       new_trade_room_text(room, a),
                       reply_markup=new_trade_kb(tid, a, room))
        if not ma:
            raise RuntimeError("no dm A")
        room["msgs"][a]  = ma.message_id
        room["chats"][a] = ma.chat.id
        mb = safe_call(bot.send_message, b,
                       new_trade_room_text(room, b),
                       reply_markup=new_trade_kb(tid, b, room))
        if not mb:
            raise RuntimeError("no dm B")
        room["msgs"][b]  = mb.message_id
        room["chats"][b] = mb.chat.id
    except Exception:
        TRADE_ROOMS.pop(tid, None)
        safe_call(bot.send_message, a,
                  "❌ Не удалось написать игроку в ЛС. Пусть он сначала запустит бота (/start).")
        return None
    return tid

# ========================= ОБРАБОТЧИК ТЕКСТА =========================
def handle_text(message):
    if message.from_user and message.from_user.is_bot:
        register_chat(message)
        return

    u = register_user(message)
    register_chat(message)

    if getattr(message, "is_automatic_forward", False):
        safe_call(bot.reply_to, message, "🎴 Напиши <b>Эксперимент</b>, чтобы получить карточку!")
        return

    raw = (message.text or message.caption or "").strip()
    if not raw:
        return

    clean = re.sub(r"^/([a-zа-яё_]+)@\S+", r"/\1", raw, flags=re.I).strip()
    if BOT_USERNAME:
        clean = re.sub(r"^@" + re.escape(BOT_USERNAME) + r"\b\s*", "", clean, flags=re.I)
    low = clean.lower()
    uid = message.from_user.id if message.from_user else 0

    COMMAND_WORDS = {
        "помощь", "нпом", "нпомощь", "help", "/help",
        "профиль", "проф", "profile",
        "бонус", "bonus",
        "топ", "топс", "топн", "топг", "top",
        "магазин", "shop",
        "инвентарь", "инв", "инве", "inv",
        "обмен",
        "реферал", "рефералы", "рефссылка", "реф", "ref",
        "индекс",
        "меню", "menu",
        CARD_WORD,
        "кейсы", "кейс", "cases",
        "битва", "battle",
    }
    _is_command = (
        low in COMMAND_WORDS
        or low.startswith("/start")
        or low.startswith("промо ")
        or low.startswith("продать")
        or low.startswith("ответ ")
        or low.startswith("вдм ")
    or low in ("битва", "battle")
    )
    if uid and not is_admin(uid) and _is_command:
        ban = get_ban(uid)
        if ban:
            left = ban["banned_until"] - time.time()
            safe_call(bot.reply_to, message,
                      f"🚫 <b>Ты заблокирован.</b> До: <b>{fmt_until(ban['banned_until'])}</b> (осталось {fmt_time(left)})")
            return

    # ---------- меню: ожидание ввода промокода / обмена ----------
    if uid in MENU_STATE and message.chat.type == "private":
        mst = MENU_STATE.pop(uid)
        if low in ("отмена", "cancel"):
            safe_call(bot.reply_to, message, "❌ Отменено.")
            return
        if mst == "promo":
            code = clean.strip().upper()
            p = promo_info(code)
            if not p:
                safe_call(bot.reply_to, message, "❌ Промокод не найден.")
                return
            if not p["active"]:
                safe_call(bot.reply_to, message, "❌ Промокод деактивирован.")
                return
            if p["rlimit"] > 0 and p["used"] >= p["rlimit"]:
                safe_call(bot.reply_to, message, "❌ Лимит активаций исчерпан.")
                return
            conn = db()
            already = conn.execute("SELECT 1 FROM promo_used WHERE code=? AND user_id=?", (code, uid)).fetchone()
            conn.close()
            if already:
                safe_call(bot.reply_to, message, "❌ Ты уже активировал этот промокод.")
                return
            result = apply_reward(uid, p["reward"])
            with db_lock:
                conn = db()
                conn.execute("INSERT OR IGNORE INTO promo_used (code, user_id) VALUES (?,?)", (code, uid))
                conn.execute("UPDATE promo SET used=used+1 WHERE code=?", (code,))
                conn.commit()
                conn.close()
            if isinstance(result, tuple) and result[0] == "CARD":
                safe_call(bot.send_photo, message.chat.id, result[2], caption=result[1],
                          reply_to_message_id=message.message_id)
            else:
                safe_call(bot.reply_to, message, f"✅ {result}")
            return
        if mst == "trade":
            target = find_user_by_ref(clean)
            if not target:
                safe_call(bot.reply_to, message,
                          "❌ Игрок не найден. Проверь @username/ID — игрок должен был запускать бота (/start).")
                return
            if target["user_id"] == uid:
                safe_call(bot.reply_to, message, "❌ С самим собой обменяться нельзя.")
                return
            if user_in_trade(uid) or user_in_trade(target["user_id"]):
                safe_call(bot.reply_to, message, "⚠️ У вас уже есть активный обмен.")
                return
            iid = send_trade_invite(uid, target["user_id"], from_chat_id=message.chat.id)
            if iid:
                safe_call(bot.reply_to, message,
                          f"✅ Приглашение отправлено игроку <b>{esc(target['nickname'])}</b>!\n"
                          f"Ожидайте ответа.")
            else:
                safe_call(bot.reply_to, message,
                          "❌ Не удалось отправить приглашение. Пусть игрок запустит бота (/start).")
            return

    # ---------- обмен v3: ожидание ввода монет ----------
    if uid in TRADE_STATE and message.chat.type == "private":
        st = TRADE_STATE.pop(uid)
        if low in ("отмена", "cancel"):
            safe_call(bot.reply_to, message, "❌ Ввод отменён.")
            return
        room = TRADE_ROOMS.get(st["tid"])
        if not room or uid not in (room["a"], room["b"]) or room["phase"] == "done":
            safe_call(bot.reply_to, message, "⚠️ Обмен уже неактивен.")
            return
        if st["step"] == "coins":
            if not clean.isdigit():
                safe_call(bot.reply_to, message, "❌ Напиши сумму числом.")
                return
            val = int(clean)
            u_trade = get_user(uid)
            free = u_trade["coins"] - room["offers"][uid]["coins"]
            if val <= 0 or val > free:
                safe_call(bot.reply_to, message, f"❌ Нельзя добавить. Свободно: {free}$.")
                return
            room["offers"][uid]["coins"] += val
            new_trade_push(room)
            safe_call(bot.reply_to, message, "✅ Монеты добавлены!")
            return





    # ---------- битва PvP: ожидание ввода цели ----------
    if uid in BATTLE_SELECT and message.chat.type == "private":
        bst = BATTLE_SELECT.pop(uid)
        if low in ("отмена", "cancel"):
            safe_call(bot.reply_to, message, "❌ Отменено.")
            return
        if bst.get("step") == "target":
            target_bv = find_user_by_ref(clean)
            if not target_bv:
                safe_call(bot.reply_to, message, "❌ Игрок не найден. Проверь @username или ID.")
                return
            if target_bv["user_id"] == uid:
                safe_call(bot.reply_to, message, "❌ Нельзя сразиться с самим собой.")
                return
            u_bv = get_user(uid)
            if battle_cd_left(u_bv) > 0:
                safe_call(bot.reply_to, message, f"⏳ Битва доступна через {fmt_time(battle_cd_left(u_bv))}.")
                return
            b_uid_bv = target_bv["user_id"]
            BATTLE_SEQ[0] += 1
            bid_bv = BATTLE_SEQ[0]
            BATTLE_CHALLENGES[bid_bv] = {
                "a": uid, "b": b_uid_bv,
                "a_card": None, "b_card": None,
                "a_chat": message.chat.id, "b_chat": b_uid_bv,
                "phase": "invite", "expires": time.time() + 300,
            }
            kb_inv_bv = types.InlineKeyboardMarkup(row_width=2)
            kb_inv_bv.add(
                types.InlineKeyboardButton("✅ Принять",   callback_data=f"battle:invite:accept:{bid_bv}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"battle:invite:decline:{bid_bv}"),
            )
            bname_bv = esc(u_bv["nickname"]) if u_bv else str(uid)
            try:
                safe_call(bot.send_message, b_uid_bv,
                          f"⚔️ <b>{bname_bv}</b> вызывает тебя на битву карт!",
                          reply_markup=kb_inv_bv)
            except Exception:
                BATTLE_CHALLENGES.pop(bid_bv, None)
                safe_call(bot.reply_to, message, "❌ Не удалось отправить вызов. Пусть игрок запустит /start.")
                return
            safe_call(bot.reply_to, message,
                      f"✅ Вызов отправлен игроку <b>{esc(target_bv['nickname'])}</b>!")
        return

    if low in ("/start", "старт") or raw.lower().startswith("/start "):
        u = u or get_user(uid)
        ref_m = re.match(r"^/start\s+ref_(\d+)$", raw.strip(), re.I)
        if ref_m and uid:
            referrer_id = int(ref_m.group(1))
            u_check = get_user(uid)
            is_new = u_check and (time.time() - u_check["created"]) < 90
            if is_new:
                coins_given, new_level = process_referral(referrer_id, uid)
                if coins_given > 0:
                    referrer_u = get_user(referrer_id)
                    if referrer_u:
                        try:
                            safe_call(bot.send_message, referrer_id,
                                      f"🎉 По твоей ссылке зарегистрировался <b>{esc(u_check['nickname'])}</b>!\n"
                                      f"🔢 Уровень ссылки: <b>{new_level}</b>\n"
                                      f"💰 Начислено: <b>{coins_given} монет</b>")
                        except Exception:
                            pass
        safe_call(bot.reply_to, message, txt_start(u["nickname"]), reply_markup=kb_start())
        return

    if low in ("помощь", "нпом", "нпомощь", "help", "/help"):
        safe_call(bot.reply_to, message, txt_help())
        return

    if low in ("реферал", "рефералы", "рефссылка", "реф", "ref"):
        safe_call(bot.reply_to, message, txt_ref_profile(uid))
        return

    if low == "индекс":
        if message.chat.type != "private":
            safe_call(bot.reply_to, message, "❌ Команда «Индекс» работает только в ЛС бота.")
            return
        safe_call(bot.reply_to, message, "🃏 <b>Выберите редкость:</b>", reply_markup=kb_rarities_user())
        return

    # ---------- продать карта ----------
    m_sell = re.match(r"^продать?\s+карт[уа]?\s+(.+)$", low)
    if m_sell:
        sell_arg = m_sell.group(1).strip()
        parts = sell_arg.rsplit(None, 1)
        sell_count = 1
        sell_all = False
        card_name = sell_arg
        if len(parts) == 2:
            last = parts[1]
            cand_id = find_card(parts[0])
            if last.isdigit() and cand_id is not None:
                card_name = parts[0]
                sell_count = max(1, int(last))
            elif last in ("все", "всё", "all") and cand_id is not None:
                card_name = parts[0]
                sell_all = True
        card_id = find_card(card_name)
        if card_id is None:
            safe_call(bot.reply_to, message, "❌ Карта не найдена.")
            return
        u = get_user(uid)
        owned = {cid: cnt for cid, cnt in get_user_cards(uid)}
        have = owned.get(card_id, 0)
        if have < 1:
            safe_call(bot.reply_to, message, "❌ У тебя нет этой карты.")
            return
        if sell_all:
            sell_count = have
        sell_count = min(sell_count, have)
        if sell_count < 1:
            safe_call(bot.reply_to, message, "❌ Нечего продавать.")
            return
        c = CARDS[card_id]
        unit_price = max(1, int(c[3] * 0.95)) if c[3] > 0 else max(1, int(c[2] * 2 * 0.95))
        total_price = unit_price * sell_count
        remove_card(uid, card_id, sell_count)
        upd_user(uid, coins=u["coins"] + total_price)
        qty_txt = f"x{sell_count} " if sell_count > 1 else ""
        safe_call(bot.reply_to, message,
                  f"💸 {qty_txt}<b>{esc(c[0])}</b> продана(ы) за <b>{total_price} монет</b>."
                  + (f" ({unit_price} × {sell_count})" if sell_count > 1 else ""))
        return

    if low in ("профиль", "проф", "profile"):
        u = get_user(uid)
        if not u:
            safe_call(bot.reply_to, message, "⚠️ Профиль недоступен.")
            return
        safe_call(bot.reply_to, message, txt_profile(u))
        return

    if low in ("бонус", "bonus"):
        u = get_user(uid)
        now = time.time()
        ts = u["last_bonus"] if u["last_bonus"] <= now else 0
        left = BONUS_COOLDOWN - (now - ts)
        if left > 0:
            safe_call(bot.reply_to, message, f"⏳ Бонус будет доступен через <b>{fmt_time(left)}</b>.")
            return
        mult = get_priv(u)["coin_mult"]
        coins = random.randint(100, 300) * mult
        pts = random.randint(20, 60) + u["level"] * 10
        upd_user(uid, coins=u["coins"] + coins, last_bonus=now)
        leveled, new_level = add_points(uid, pts)
        msg = f"🎁 Успешно! Получено <b>{pts} Очков</b> и <b>{coins} Монет</b> 💰"
        if leveled:
            msg += f"\n🔋 Новый уровень: <b>{new_level}</b>!"
        safe_call(bot.reply_to, message, msg)
        return

    if low in ("топ", "топс", "топн", "топг", "top"):
        u_top = get_user(uid) or u
        nick_top = esc(u_top["nickname"]) if u_top else "Игрок"
        msg = safe_call(bot.reply_to, message,
                        f"{nick_badged(uid, nick_top)}, выберите ниже топ который хотите открыть:",
                        reply_markup=kb_top_menu())
        if msg:
            TOP_MSG_OWNER[msg.message_id] = uid
        return

    if low in ("кейсы", "кейс", "cases"):
        kb = types.InlineKeyboardMarkup(row_width=1)
        for key, cr in CRATES.items():
            kb.add(types.InlineKeyboardButton(
                f"{cr['emoji']} {cr['name']} — 💰 {cr['cost']} монет",
                callback_data=f"case:view:{key}:{uid}",
            ))
        safe_call(bot.reply_to, message, "📦 <b>Кейсы</b>\nВыбери кейс:", reply_markup=kb)
        return

    if low in ("магазин", "shop"):
        msg = safe_call(bot.reply_to, message, txt_shop(), reply_markup=kb_shop())
        if msg:
            SHOP_MSG_OWNER[msg.message_id] = uid
        return

    if low in ("инвентарь", "инв", "инве", "inv"):
        rows = get_user_cards(uid)
        if not rows:
            safe_call(bot.reply_to, message,
                      "🎒 <b>Инвентарь пуст.</b>\nНапиши «эксперимент», чтобы получить карточку!")
            return
        kb, page, rows, per_page = kb_inventory(uid, 0)
        start = page * per_page
        lines = [f"🎒 <b>Ваш Инвентарь:</b> <i>стр. {page+1}</i>\n════════════════════════════"]
        for cid, cnt in rows[start:start + per_page]:
            c = CARDS[cid]
            em = RARITY_EMOJI.get(c[1], "▫️")
            lines.append(f"{em} {esc(c[0])} — {RARITY_EN.get(c[1], c[1])} (x{cnt}) | 💪 {c[2]}")
        msg = safe_call(bot.reply_to, message, "\n".join(lines), reply_markup=kb)
        if msg:
            INV_PAGES[uid] = msg.message_id
            INV_MSG_OWNER[msg.message_id] = uid
        return

    # ---------- обмен [username/id] ----------
    m_trade = re.match(r"^обмен\s+(.+)$", low)
    if m_trade:
        arg = m_trade.group(1).strip()
        if user_in_trade(uid):
            safe_call(bot.reply_to, message,
                      "⚠️ У тебя уже есть активный обмен. Сначала заверши его.")
            return
        target = find_user_by_ref(arg)
        if not target:
            safe_call(bot.reply_to, message,
                      "❌ Игрок не найден. Проверь @username/ID.")
            return
        if target["user_id"] == uid:
            safe_call(bot.reply_to, message, "❌ С самим собой обменяться нельзя.")
            return
        if user_in_trade(target["user_id"]):
            safe_call(bot.reply_to, message, "⚠️ Этот игрок уже в обмене.")
            return
        iid = send_trade_invite(uid, target["user_id"], from_chat_id=message.chat.id)
        if iid:
            safe_call(bot.reply_to, message,
                      f"✅ Приглашение отправлено игроку <b>{esc(target['nickname'])}</b>!\nОжидайте ответа.")
        else:
            safe_call(bot.reply_to, message,
                      "❌ Не удалось отправить приглашение. Пусть игрок запустит бота (/start).")
        return

    if low == "обмен":
        safe_call(bot.reply_to, message,
                  "🔄 <b>Обмен</b>\nИспользуй: <b>Обмен @username</b> или <b>Обмен ID</b>")
        return


    if low in ("меню", "menu"):
        msg = safe_call(bot.reply_to, message, "📋 <b>Меню</b>\nВыбери раздел:", reply_markup=kb_menu(uid))
        if msg:
            MENU_MSG_OWNER[msg.message_id] = uid
        return

    # ---------- промокод ----------
    m = re.match(r"^промо\s+(\S+)$", low)
    if m:
        code = m.group(1).upper()
        p = promo_info(code)
        if not p:
            safe_call(bot.reply_to, message, "❌ Промокод не найден.")
            return
        if not p["active"]:
            safe_call(bot.reply_to, message, "❌ Промокод деактивирован.")
            return
        if p["rlimit"] > 0 and p["used"] >= p["rlimit"]:
            safe_call(bot.reply_to, message, "❌ Лимит активаций исчерпан.")
            return
        conn = db()
        already = conn.execute("SELECT 1 FROM promo_used WHERE code=? AND user_id=?", (code, uid)).fetchone()
        conn.close()
        if already:
            safe_call(bot.reply_to, message, "❌ Ты уже активировал этот промокод.")
            return
        result = apply_reward(uid, p["reward"])
        with db_lock:
            conn = db()
            conn.execute("INSERT OR IGNORE INTO promo_used (code, user_id) VALUES (?,?)", (code, uid))
            conn.execute("UPDATE promo SET used=used+1 WHERE code=?", (code,))
            conn.commit()
            conn.close()
        if isinstance(result, tuple) and result[0] == "CARD":
            safe_call(bot.send_photo, message.chat.id, result[2], caption=result[1],
                      reply_to_message_id=message.message_id)
        else:
            safe_call(bot.reply_to, message, f"✅ {result}")
        return

    # ---------- вдм (Продавец) ----------
    m_vdm_card = re.match(r"^вдм\s+карта\s+(.+?)\s+(\d+)$", low)
    m_vdm_card_1 = re.match(r"^вдм\s+карта\s+(.+)$", low) if not m_vdm_card else None
    m_vdm_coins = re.match(r"^вдм\s+монеты\s+(\d+)$", low)

    if m_vdm_card or m_vdm_card_1 or m_vdm_coins:
        u = get_user(uid)
        if not u or u["privilege"] != "Продавец | Бета Тестер":
            safe_call(bot.reply_to, message, "❌ Нет доступа. Нужна привилегия <b>Продавец | Бета Тестер</b>.")
            return
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет профиля.")
            return
        tuid = message.reply_to_message.from_user.id
        if m_vdm_coins:
            val = int(m_vdm_coins.group(1))
            if val <= 0:
                safe_call(bot.reply_to, message, "❌ Сумма должна быть больше нуля.")
                return
            tu = ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
            upd_user(tuid, coins=tu["coins"] + val)
            safe_call(bot.reply_to, message, f"✅ Выдано <b>{val} монет</b> игроку <b>{esc(tu['nickname'])}</b>.")
            return
        if m_vdm_card:
            card_name = m_vdm_card.group(1).strip()
            count = int(m_vdm_card.group(2))
        else:
            card_name = m_vdm_card_1.group(1).strip()
            count = 1
        count = max(1, count)
        card_id = find_card(card_name)
        if card_id is None:
            safe_call(bot.reply_to, message, "❌ Карта не найдена. Проверь название.")
            return
        for _ in range(count):
            give_card(tuid, card_id)
        tu = ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
        cnt_now = 0
        for cid, c in get_user_cards(tuid):
            if cid == card_id:
                cnt_now = c
        text, url = card_drop_text(tu, CARDS[card_id], cnt_now, get_priv(tu)["card_cd"])
        safe_call(bot.send_photo, message.chat.id, url, caption=text,
                  reply_to_message_id=message.message_id)
        return

    # ---------- эксперимент — получить карту ----------
    if low.strip() == CARD_WORD:
        u = get_user(uid)
        now = time.time()
        cd = max(300, get_priv(u)["card_cd"])
        ts = u["last_card"] if u["last_card"] <= now else 0
        left = cd - (now - ts)
        if left > 0:
            safe_call(bot.reply_to, message, f"⏳ Следующая карта через <b>{fmt_time(left)}</b>.")
            return
        card_id = pick_card_id(uid=uid)
        leveled, new_level = give_card(uid, card_id)
        u = get_user(uid)
        cnt = 0
        for cid, c in get_user_cards(uid):
            if cid == card_id:
                cnt = c
        text, url = card_drop_text(u, CARDS[card_id], cnt, cd)
        if leveled:
            idx = text.rfind("\n\n🎁")
            lvl_txt = f"\n🔋 Новый уровень: {new_level}!"
            text = text[:idx] + lvl_txt + text[idx:]
        upd_user(uid, last_card=now)
        safe_call(bot.send_photo, message.chat.id, url, caption=text,
                  reply_to_message_id=message.message_id)
        return


# ========================= АДМИН-КОМАНДЫ =========================
def is_admin(uid):
    return uid in CREATORS

MAIN_CREATOR_ID = 5679778859

def handle_admin(message, low, uid, raw="", clean=""):
    if low in ("меню нуб", "нуб меню", "admin", "админ"):
        safe_call(bot.reply_to, message, txt_admin_menu(), reply_markup=kb_admin_menu())
        return True

    # ---- .создать карта (только главный создатель) ----
    if low.strip() == ".создать карта":
        if uid != MAIN_CREATOR_ID:
            safe_call(bot.reply_to, message, "❌ Нет доступа.")
            return True
        CARD_CREATE_STATE[uid] = True
        safe_call(
            bot.reply_to, message,
            "♾️ <b>Создание Карты</b>\n"
            "___________________\n"
            "Пример:\n"
            "[Фотография Карты]\n"
            "Название Карты: имя\n"
            "Редкость Карты: обычный | необычный | редкий | эпический | Легендарный | мифический | ???\n"
            "Стоимость Карты: \n"
            "Сила Карты: \n"
            "Опыт Карты: \n"
            "___________________\n"
            "📸 Отправь фото карты с подписью в этом формате следующим сообщением.\n"
            "Напиши «отмена» для отмены.",
        )
        return True

    if low.strip() == "$ database odev true":
        if uid != MAIN_CREATOR_ID:
            safe_call(bot.reply_to, message, "❌ Нет доступа.")
            return True
        if not os.path.isfile(DB_NAME):
            safe_call(bot.reply_to, message, "❌ Файл базы данных не найден.")
            return True
        try:
            ts_str = datetime.now(tz=MSK).strftime("%Y-%m-%d_%H-%M-%S")
            caption = f"🗄 <b>База данных NooB Bot</b>\n📅 {ts_str}\n📦 {os.path.getsize(DB_NAME)} байт"
            with open(DB_NAME, "rb") as f:
                safe_call(bot.send_document, uid, f, caption=caption, visible_file_name=f"noob_bot_{ts_str}.db")
            if message.chat.id != uid:
                safe_call(bot.reply_to, message, "✅ БД отправлена тебе в ЛС.")
        except Exception as e:
            safe_call(bot.reply_to, message, f"❌ Ошибка отправки БД: {esc(str(e)[:200])}")
        return True

    # ---- .бан / Swoon (новая команда) ----
    # Формат (ответом на сообщение):
    #   .бан 1д
    #   Причина бана (необязательно)
    # Алиас: Swoon 1д
    _raw_lines = raw.strip().split("\n", 1)
    _first_line = _raw_lines[0].strip()
    _reason = _raw_lines[1].strip() if len(_raw_lines) > 1 else ""

    m_newban = re.match(
        r"^(?:\.бан|swoon)\s+(.+?)(?:\s+(.+))?$",
        _first_line,
        re.IGNORECASE,
    )
    if m_newban:
        duration_str = m_newban.group(1).strip()
        inline_reason = (m_newban.group(2) or "").strip()
        reason = inline_reason or _reason
        seconds = parse_ban_duration(duration_str)
        if seconds is None:
            safe_call(
                bot.reply_to, message,
                "❌ Не распознал время.\nПримеры: <b>30сек</b> · <b>10мин</b> · <b>2ч</b> · <b>1д</b>",
            )
            return True
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return True
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 Ботов банить бессмысленно.")
            return True
        tuid = message.reply_to_message.from_user.id
        if tuid in CREATORS:
            safe_call(bot.reply_to, message, "❌ Нельзя банить создателя.")
            return True
        until = ban_user(tuid, seconds, reason=reason)
        tu = ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
        reason_line = f"\n📝 Причина: <b>{esc(reason)}</b>" if reason else ""
        safe_call(
            bot.reply_to, message,
            f"🚫 <b>{esc(tu['nickname'])}</b> заблокирован."
            f"\n⏱ На: <b>{duration_str}</b>"
            f"\nДо: <b>{fmt_until(until)}</b>"
            f"{reason_line}",
        )
        try:
            safe_call(
                bot.send_message, tuid,
                f"🚫 <b>Ты заблокирован в боте.</b>"
                f"\n⏱ На: <b>{duration_str}</b>"
                f"\nДо: <b>{fmt_until(until)}</b>"
                f"{reason_line}",
            )
        except Exception:
            pass
        return True

    # ---- .разбан / .unban (новая команда) ----
    if _first_line.lower() in (".разбан", ".unban"):
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return True
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет банов.")
            return True
        tuid = message.reply_to_message.from_user.id
        unban_user(tuid)
        tu = get_user(tuid)
        name = esc(tu["nickname"]) if tu else str(tuid)
        safe_call(bot.reply_to, message, f"✅ <b>{name}</b> разбанен.")
        try:
            safe_call(bot.send_message, tuid, "✅ <b>Ты был разбанен администратором.</b>")
        except Exception:
            pass
        return True

    if low.strip() == "!снос бота":
        if uid != MAIN_CREATOR_ID:
            safe_call(bot.reply_to, message, "❌ Нет доступа.")
            return True
        safe_call(bot.reply_to, message, "💣 <b>Снос бота запущен.</b> Рассылаю обратный отсчёт...")
        def _shutdown_sequence(src_uid=uid):
            import sys
            for secs_left in (3, 2, 1):
                try:
                    do_broadcast_text(f"⚠️ <b>СНОС БОТА ЧЕРЕЗ {secs_left}</b>")
                except Exception:
                    pass
                time.sleep(1)
            try:
                do_broadcast_text("💀 <b>Бот Взломан, Всем Пока</b>")
            except Exception:
                pass
            try:
                safe_call(bot.send_message, src_uid, "✅ Обратный отсчёт завершён. Выключаюсь.")
            except Exception:
                pass
            time.sleep(0.5)
            sys.exit(0)
        try:
            threading.Thread(target=_shutdown_sequence, daemon=False).start()
        except RuntimeError:
            _shutdown_sequence()
        return True

    m_b = re.match(r"^/b\s+(.+)$", clean, re.DOTALL)
    if not m_b:
        m_b = re.match(r"^/b\s+(.+)$", raw, re.DOTALL)
    if m_b:
        btext = m_b.group(1).strip()
        if not btext:
            safe_call(bot.reply_to, message, "❌ Текст не может быть пустым.\nПример: /b Привет всем!")
            return True
        safe_call(bot.reply_to, message, "📨 Рассылка запущена...")
        def _run_b(text=btext, src_msg=message):
            try:
                ok, fail = do_broadcast_text(text)
                safe_call(bot.send_message, src_msg.chat.id, f"✅ Рассылка завершена!\n📤 Доставлено: {ok}\n❌ Не доставлено: {fail}")
            except Exception as _e:
                safe_call(bot.send_message, src_msg.chat.id, f"⚠️ Ошибка рассылки: {esc(str(_e)[:200])}")
        try:
            threading.Thread(target=_run_b, daemon=True).start()
        except RuntimeError:
            _run_b()
        return True

    if low == "стата":
        conn = db()
        players = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_coins = conn.execute("SELECT COALESCE(SUM(coins),0) FROM users").fetchone()[0]
        conn.close()
        safe_call(bot.reply_to, message,
                  f"📊 <b>Статистика бота:</b>\n"
                  f"👤 Игроков: {players}\n"
                  f"💰 Монет в игре: {total_coins}\n"
                  f"😶‍🌫️ Статус Бота: Активный ✅")
        return True

    if low == "рассылка список":
        if message.chat.type != "private":
            safe_call(bot.reply_to, message, "❌ Эту команду пиши мне в ЛС.")
            return True
        rows = get_all_chats()
        if not rows:
            safe_call(bot.reply_to, message, "📭 Список чатов пуст.")
            return True
        PAGE_SIZE = 20
        chunks = [rows[i:i+PAGE_SIZE] for i in range(0, len(rows), PAGE_SIZE)]
        for idx, chunk in enumerate(chunks):
            lines = [f"📋 <b>Чаты для рассылки</b> [{idx+1}/{len(chunks)}]\n{'━'*28}"]
            for r in chunk:
                ident = r["username"] or r["chat_id"]
                ctype = "👥" if r["ctype"] == "group" else ("📢" if r["ctype"] == "supergroup" else "💬")
                title = esc(r["title"])[:30]
                lines.append(f"{ctype} {title} — <code>{ident}</code>")
            safe_call(bot.send_message, message.chat.id, "\n".join(lines))
        safe_call(bot.send_message, message.chat.id, f"📊 Всего чатов: <b>{len(rows)}</b>")
        return True

    if low == "рассылка общий":
        ADMIN_STATE[uid] = {"target": "all"}
        safe_call(bot.reply_to, message,
                  "📨 Рассылка во <b>ВСЕ</b> чаты.\nСкинь следующим сообщением контент.\nНапиши «отмена» для отмены.")
        return True

    m = re.match(r"^рассылка\s+(.+)$", low)
    if m:
        arg = m.group(1).strip()
        if arg == "список":
            return False
        target = parse_chat_arg(arg)
        if target is None:
            safe_call(bot.reply_to, message, "❌ Не удалось распознать чат. Используй @чат, ссылку или ID.")
            return True
        ADMIN_STATE[uid] = {"target": target}
        safe_call(bot.reply_to, message,
                  f"📨 Рассылка в чат: <b>{esc(arg)}</b>.\nСкинь следующим сообщением контент.\nНапиши «отмена» для отмены.")
        return True

    if low == "проф":
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return True
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет профиля.")
            return True
        tuid = message.reply_to_message.from_user.id
        u = ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
        safe_call(bot.reply_to, message, txt_profile(u))
        return True

    m = re.match(r"^вд\s+карта\s+(.+)$", low)
    if m:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return True
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет профиля.")
            return True
        tuid = message.reply_to_message.from_user.id
        name = m.group(1).strip()
        card_id = find_card(name)
        if card_id is None:
            safe_call(bot.reply_to, message, "❌ Карта не найдена.")
            return True
        leveled, new_level = give_card(tuid, card_id)
        u = ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
        cnt = 0
        for cid, c in get_user_cards(tuid):
            if cid == card_id:
                cnt = c
        text, url = card_drop_text(u, CARDS[card_id], cnt, get_priv(u)["card_cd"])
        if leveled:
            idx = text.rfind("\n\n🎁")
            text = text[:idx] + f"\n🔋 Новый уровень: {new_level}!" + text[idx:]
        safe_call(bot.send_photo, message.chat.id, url, caption=text, reply_to_message_id=message.message_id)
        return True

    m = re.match(r"^вд\s+(монеты|очки|уровни|сила)\s+(\d+)$", low)
    if m:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return True
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет профиля.")
            return True
        tuid = message.reply_to_message.from_user.id
        typ = m.group(1)
        val = int(m.group(2))
        u = ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
        if typ == "монеты":
            upd_user(tuid, coins=u["coins"] + val)
        elif typ == "очки":
            add_points(tuid, val)
        elif typ == "уровни":
            upd_user(tuid, level=u["level"] + val)
        elif typ == "сила":
            upd_user(tuid, strength=u["strength"] + val)
        safe_call(bot.reply_to, message, f"✅ Выдано <b>{esc(typ)} +{val}</b> игроку.")
        return True

    m = re.match(r"^вд\s+привилегия(?:\s+(.+))?$", low)
    if m:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return True
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет профиля.")
            return True
        tuid = message.reply_to_message.from_user.id
        name = (m.group(1) or "").strip()
        u = ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
        if not name:
            upd_user(tuid, privilege="Игрок")
            safe_call(bot.reply_to, message, f"✅ Привилегия снята. Теперь: <b>Игрок</b>")
            return True
        canon = None
        for p in PRIVILEGES:
            if p.lower() == name.lower():
                canon = p
                break
        if canon is None:
            avail = " | ".join(PRIVILEGES.keys())
            safe_call(bot.reply_to, message, f"❌ Такой привилегии нет.\nДоступные: <b>{esc(avail)}</b>")
            return True
        upd_user(tuid, privilege=canon)
        safe_call(bot.reply_to, message, f"✅ Игроку выдана привилегия: <b>{esc(canon)}</b>")
        return True

    if low == "ресет":
        if not message.reply_to_message or not message.reply_to_message.from_user:
            tuid = uid
            tu = get_user(tuid)
            if not tu:
                safe_call(bot.reply_to, message, "❌ Профиль не найден.")
                return True
        elif message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет профиля.")
            return True
        else:
            tuid = message.reply_to_message.from_user.id
            tu = get_user(tuid)
            if not tu:
                safe_call(bot.reply_to, message, "❌ Игрок не найден.")
                return True
        keep_priv = "Создатель" if tuid in CREATORS else tu["privilege"]
        with db_lock:
            conn = db()
            conn.execute("DELETE FROM user_cards WHERE user_id=?", (tuid,))
            conn.commit()
            conn.close()
        upd_user(tuid, coins=0, points=0, strength=0, level=0, cards_received=0,
                 last_card=0, last_bonus=0, privilege=keep_priv)
        safe_call(bot.reply_to, message,
                  f"♻️ Профиль <b>{esc(tu['nickname'])}</b> полностью сброшен.\n"
                  f"👑 Привилегия сохранена: <b>{esc(keep_priv)}</b>")
        return True

    if low == "вд ппб":
        if not message.reply_to_message or not message.reply_to_message.from_user:
            safe_call(bot.reply_to, message, "❌ Ответь на сообщение игрока.")
            return True
        if message.reply_to_message.from_user.is_bot:
            safe_call(bot.reply_to, message, "🤖 У ботов нет профиля.")
            return True
        tuid = message.reply_to_message.from_user.id
        ensure_user_exists(tuid, message.reply_to_message.from_user.first_name or "Игрок")
        upd_user(tuid, privilege="Продавец | Бета Тестер")
        safe_call(bot.reply_to, message, "✅ Выдана привилегия: <b>Продавец | Бета Тестер</b>")
        try:
            safe_call(bot.send_message, tuid,
                      "🎉 Тебе выдана привилегия <b>Продавец | Бета Тестер</b>!\n\n"
                      "Что тебе доступно:\n"
                      "• +35% удача на редкие карты\n"
                      "• Кулдаун карты: 30 мин\n"
                      "• х2 монеты с бонуса\n"
                      "• Команда <b>вдм карта [название] [кол-во]</b> — выдать карту игроку (ответом)\n"
                      "• Команда <b>вдм монеты [сумма]</b> — выдать монеты игроку (ответом)")
        except Exception:
            pass
        return True

    if low == "карты список":
        safe_call(bot.reply_to, message, "🃏 <b>Выберите редкость:</b>", reply_markup=kb_rarities())
        return True

    m_take = re.match(r"^забрать\s+монеты(?:\s+(.+))?$", low)
    if m_take:
        arg = (m_take.group(1) or "").strip()
        tuid = None
        amount = 0
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.is_bot:
                safe_call(bot.reply_to, message, "🤖 У ботов нет монет.")
                return True
            tuid = message.reply_to_message.from_user.id
            if arg.isdigit():
                amount = int(arg)
            else:
                safe_call(bot.reply_to, message, "❌ Укажи сумму числом.\nПример: <b>забрать монеты 500</b> (ответом на сообщение)")
                return True
        else:
            parts = arg.split()
            if len(parts) < 2:
                safe_call(bot.reply_to, message,
                          "❌ Формат:\n• ответом на сообщение: <b>забрать монеты [кол-во]</b>\n• по юзернейму: <b>забрать монеты @username [кол-во]</b>")
                return True
            ref_str = parts[0]
            num_str = parts[-1]
            if not num_str.isdigit():
                safe_call(bot.reply_to, message, "❌ Последний аргумент должен быть числом.")
                return True
            amount = int(num_str)
            target = find_user_by_ref(ref_str)
            if not target:
                safe_call(bot.reply_to, message, "❌ Игрок не найден.")
                return True
            tuid = target["user_id"]
        if amount <= 0:
            safe_call(bot.reply_to, message, "❌ Сумма должна быть больше нуля.")
            return True
        if tuid in CREATORS:
            safe_call(bot.reply_to, message, "❌ Нельзя забирать монеты у создателей.")
            return True
        tu = get_user(tuid)
        if not tu:
            safe_call(bot.reply_to, message, "❌ Игрок не найден в базе.")
            return True
        actually_take = min(amount, tu["coins"])
        upd_user(tuid, coins=tu["coins"] - actually_take)
        tu2 = get_user(tuid)
        safe_call(bot.reply_to, message,
                  f"💸 У <b>{esc(tu['nickname'])}</b> (ID: {tuid}) забрано <b>{actually_take}$</b>.\n"
                  f"💰 Остаток: <b>{tu2['coins']}$</b>")
        try:
            safe_call(bot.send_message, tuid,
                      f"📢 Создатель забрал у тебя <b>{actually_take} монет</b>.\n💰 Остаток: <b>{tu2['coins']}$</b>")
        except Exception:
            pass
        return True

    m = re.match(r"^промо\s+создать\s+(.+)$", low)
    if m:
        parts = m.group(1).strip().split()
        if len(parts) < 3:
            safe_call(bot.reply_to, message, "❌ Формат: промо создать КОД награда ... [лимит]")
            return True
        code = parts[0].upper()
        limit = 0
        reward = " ".join(parts[1:])
        if parts[-1].isdigit():
            test_reward = " ".join(parts[1:-1])
            if valid_reward(test_reward):
                limit = int(parts[-1])
                reward = test_reward
        if not valid_reward(reward):
            safe_call(bot.reply_to, message, "❌ Неверная награда.")
            return True
        with db_lock:
            conn = db()
            conn.execute("INSERT OR REPLACE INTO promo (code, reward, rlimit, used, active, created) VALUES (?,?,?,?,?,?)",
                         (code, reward, limit, 0, 1, time.time()))
            conn.commit()
            conn.close()
        safe_call(bot.reply_to, message, f"✅ Промокод <b>{esc(code)}</b> создан!\nНаграда: {esc(reward)} | Лимит: {limit or '∞'}")
        return True

    m = re.match(r"^промо\s+удалить\s+(\S+)$", low)
    if m:
        code = m.group(1).upper()
        with db_lock:
            conn = db()
            conn.execute("DELETE FROM promo WHERE code=?", (code,))
            conn.execute("DELETE FROM promo_used WHERE code=?", (code,))
            conn.commit()
            conn.close()
        safe_call(bot.reply_to, message, f"🗑 Промокод <b>{esc(code)}</b> удалён.")
        return True

    m = re.match(r"^промо\s+ред\s+(\S+)\s+награда\s+(.+)$", low)
    if m:
        code = m.group(1).upper()
        rw = m.group(2).strip()
        if not valid_reward(rw):
            safe_call(bot.reply_to, message, "❌ Неверная награда.")
            return True
        with db_lock:
            conn = db()
            conn.execute("UPDATE promo SET reward=? WHERE code=?", (rw, code))
            conn.commit()
            conn.close()
        safe_call(bot.reply_to, message, f"✅ Промокод <b>{esc(code)}</b> обновлён.")
        return True

    m = re.match(r"^промо\s+ред\s+(\S+)\s+лимит\s+(\d+)$", low)
    if m:
        code = m.group(1).upper()
        lim = int(m.group(2))
        with db_lock:
            conn = db()
            conn.execute("UPDATE promo SET rlimit=? WHERE code=?", (lim, code))
            conn.commit()
            conn.close()
        safe_call(bot.reply_to, message, f"✅ Лимит промокода <b>{esc(code)}</b> = {lim}")
        return True

    m = re.match(r"^промо\s+ред\s+(\S+)\s+статус\s+(вкл|выкл)$", low)
    if m:
        code = m.group(1).upper()
        st = 1 if m.group(2) == "вкл" else 0
        with db_lock:
            conn = db()
            conn.execute("UPDATE promo SET active=? WHERE code=?", (st, code))
            conn.commit()
            conn.close()
        safe_call(bot.reply_to, message, f"✅ Промокод <b>{esc(code)}</b> — {'включён' if st else 'выключен'}.")
        return True

    if low == "промо список":
        conn = db()
        rows = conn.execute("SELECT code, reward, rlimit, used, active FROM promo ORDER BY code").fetchall()
        conn.close()
        if not rows:
            safe_call(bot.reply_to, message, "📭 Промокодов нет.")
            return True
        lines = ["🎟 <b>ПРОМОКОДЫ</b>\n━━━━━━━━━━━━━━━━━━━━"]
        for r in rows:
            status = "🟢" if r["active"] else "🔴"
            lim = f"{r['used']}/{r['rlimit']}" if r["rlimit"] > 0 else f"{r['used']}/∞"
            lines.append(f"{status} <b>{esc(r['code'])}</b> — {esc(r['reward'])} — {lim}")
        safe_call(bot.reply_to, message, "\n".join(lines))
        return True

    m = re.match(r"^промо\s+инфо\s+(\S+)$", low)
    if m:
        code = m.group(1).upper()
        p = promo_info(code)
        if not p:
            safe_call(bot.reply_to, message, "❌ Промокод не найден.")
            return True
        status = "🟢 Активен" if p["active"] else "🔴 Выключен"
        lim = f"{p['used']}/{p['rlimit']}" if p["rlimit"] > 0 else f"{p['used']}/∞"
        safe_call(bot.reply_to, message,
                  f"🎟 <b>{esc(code)}</b>\nНаграда: {esc(p['reward'])}\nЛимит: {lim}\nСтатус: {status}")
        return True

    return False


# ========================= CALLBACKS =========================
@guard
def callback_handler(call):
    data = call.data
    uid = call.from_user.id
    chat_id = call.message.chat.id

    ensure_user_exists(uid, call.from_user.first_name or "Игрок")

    if data.startswith("admin:") or data == "back:help":
        if not is_admin(uid):
            if data.startswith("admin:"):
                safe_call(bot.answer_callback_query, call.id, "❌ Нет доступа. Это панель администратора.", show_alert=True)
                return
        if uid in ADMIN_STATE:
            ADMIN_STATE.pop(uid, None)

    # ---------- инвентарь ----------
    if data == "inv:noop":
        safe_call(bot.answer_callback_query, call.id)
        return

    # ---------- меню ----------
    m_menu = re.match(r"^menu:(\d+):(.+)$", data)
    if m_menu:
        owner = int(m_menu.group(1))
        action = m_menu.group(2)
        if uid != owner:
            safe_call(bot.answer_callback_query, call.id,
                      "⛔ Это не твоё меню. Напиши «Меню», чтобы открыть своё.", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id)
        if action == "profile":
            u_m = get_user(uid)
            if u_m:
                safe_call(bot.send_message, chat_id, txt_profile(u_m))
        elif action == "inv":
            rows_m = get_user_cards(uid)
            if not rows_m:
                safe_call(bot.send_message, chat_id,
                          "🎒 <b>Инвентарь пуст.</b>\nНапиши «эксперимент», чтобы получить карточку!")
            else:
                kb_i, page_i, rows_i, per_i = kb_inventory(uid, 0)
                start_i = page_i * per_i
                lines_i = [f"🎒 <b>Ваш Инвентарь:</b> <i>стр. 1</i>\n════════════════════════════"]
                for cid_i, cnt_i in rows_i[start_i:start_i + per_i]:
                    c_i = CARDS[cid_i]
                    em_i = RARITY_EMOJI.get(c_i[1], "▫️")
                    lines_i.append(f"{em_i} {esc(c_i[0])} — {RARITY_EN.get(c_i[1], c_i[1])} (x{cnt_i}) | 💪 {c_i[2]}")
                msg_i = safe_call(bot.send_message, chat_id, "\n".join(lines_i), reply_markup=kb_i)
                if msg_i:
                    INV_PAGES[uid] = msg_i.message_id
                    INV_MSG_OWNER[msg_i.message_id] = uid
        elif action == "shop":
            msg_s = safe_call(bot.send_message, chat_id, txt_shop(), reply_markup=kb_shop())
            if msg_s:
                SHOP_MSG_OWNER[msg_s.message_id] = uid
        elif action == "cases":
            kb_c = types.InlineKeyboardMarkup(row_width=1)
            for key_c, cr_c in CRATES.items():
                kb_c.add(types.InlineKeyboardButton(
                    f"{cr_c['emoji']} {cr_c['name']} — 💰 {cr_c['cost']} монет",
                    callback_data=f"case:view:{key_c}:{uid}",
                ))
            safe_call(bot.send_message, chat_id, "📦 <b>Кейсы</b>\nВыбери кейс:", reply_markup=kb_c)
        elif action == "promo":
            MENU_STATE[uid] = "promo"
            safe_edit(chat_id, call.message.message_id,
                      "🎟 Введите промокод:\n<i>«отмена» — отменить</i>",
                      fallback_new=True)
        elif action == "trade":
            if user_in_trade(uid):
                safe_call(bot.answer_callback_query, call.id,
                          "⚠️ У тебя уже есть активный обмен.", show_alert=True)
            else:
                MENU_STATE[uid] = "trade"
                safe_edit(chat_id, call.message.message_id,
                          "🔄 Введи @username или ID игрока:\n<i>«отмена» — отменить</i>",
                          fallback_new=True)
        elif action == "bonus":
            u_bn = get_user(uid)
            now_bn = time.time()
            ts_bn = u_bn["last_bonus"] if u_bn["last_bonus"] <= now_bn else 0
            left_bn = BONUS_COOLDOWN - (now_bn - ts_bn)
            if left_bn > 0:
                safe_call(bot.answer_callback_query, call.id,
                          f"Доступно через {fmt_time(left_bn)}", show_alert=True)
            else:
                mult_bn = get_priv(u_bn)["coin_mult"]
                coins_bn = random.randint(100, 300) * mult_bn
                pts_bn = random.randint(20, 60) + u_bn["level"] * 10
                upd_user(uid, coins=u_bn["coins"] + coins_bn, last_bonus=now_bn)
                leveled_bn, nlvl_bn = add_points(uid, pts_bn)
                msg_bn = f"Получено: {pts_bn} Очков и {coins_bn} Монет"
                if leveled_bn:
                    msg_bn += f"\nНовый уровень: {nlvl_bn}!"
                safe_call(bot.answer_callback_query, call.id, msg_bn, show_alert=True)
        elif action == "top":
            u_mt = get_user(uid)
            nick_mt = esc(u_mt["nickname"]) if u_mt else "Игрок"
            msg_t = safe_call(bot.send_message, chat_id,
                              f"{nick_badged(uid, nick_mt)}, выберите ниже топ который хотите открыть:",
                              reply_markup=kb_top_menu())
            if msg_t:
                TOP_MSG_OWNER[msg_t.message_id] = uid
        return

    # ---------- кейсы ----------
    m_case_view = re.match(r"^case:view:(\w+):(\d+)$", data)
    if m_case_view:
        key_cv, owner_cv = m_case_view.group(1), int(m_case_view.group(2))
        if uid != owner_cv:
            safe_call(bot.answer_callback_query, call.id,
                      "⛔ Это не твоё меню кейсов.", show_alert=True)
            return
        cr_cv = CRATES.get(key_cv)
        if not cr_cv:
            safe_call(bot.answer_callback_query, call.id, "❌ Кейс не найден.", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id)
        lines_cv = [f"{cr_cv['emoji']} <b>{cr_cv['name']}</b>",
                    f"💰 Стоимость: <b>{cr_cv['cost']} монет</b>",
                    f"",
                    f"📊 Содержимое:"]
        for item_cv in cr_cv["cards"]:
            cid_cv = find_card(item_cv["card"])
            if cid_cv is not None:
                c_cv = CARDS[cid_cv]
                rar_cv = RARITY_EN.get(c_cv[1], c_cv[1])
                lines_cv.append(f"🃏 {esc(c_cv[0])} — {rar_cv} | 📊 {item_cv['chance']}%")
        u_cv = get_user(uid)
        coins_cv = u_cv["coins"] if u_cv else 0
        lines_cv.append(f"\n💰 У тебя: <b>{coins_cv} монет</b>")
        kb_cv = types.InlineKeyboardMarkup(row_width=1)
        kb_cv.add(types.InlineKeyboardButton(
            f"🔓 Открыть за {cr_cv['cost']} монет",
            callback_data=f"case:open:{key_cv}:{uid}",
        ))
        kb_cv.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"case:back:{uid}"))
        safe_edit(chat_id, call.message.message_id, "\n".join(lines_cv),
                  reply_markup=kb_cv, fallback_new=True)
        return

    m_case_open = re.match(r"^case:open:(\w+):(\d+)$", data)
    if m_case_open:
        key_co, owner_co = m_case_open.group(1), int(m_case_open.group(2))
        if uid != owner_co:
            safe_call(bot.answer_callback_query, call.id,
                      "⛔ Это не твоё меню кейсов.", show_alert=True)
            return
        cr_co = CRATES.get(key_co)
        if not cr_co:
            safe_call(bot.answer_callback_query, call.id, "❌ Кейс не найден.", show_alert=True)
            return
        u_co = get_user(uid)
        if not u_co or u_co["coins"] < cr_co["cost"]:
            safe_call(bot.answer_callback_query, call.id,
                      f"❌ Недостаточно монет. Нужно: {cr_co['cost']}.", show_alert=True)
            return
        # Weighted random pick
        pool_co = cr_co["cards"]
        total_w = sum(item["chance"] for item in pool_co)
        r_co = random.uniform(0, total_w)
        acc_co = 0.0
        picked_co = pool_co[-1]
        for item_co in pool_co:
            acc_co += item_co["chance"]
            if r_co < acc_co:
                picked_co = item_co
                break
        card_id_co = find_card(picked_co["card"])
        if card_id_co is None:
            safe_call(bot.answer_callback_query, call.id, "❌ Ошибка кейса. Напишите администратору.", show_alert=True)
            return
        # Deduct coins
        upd_user(uid, coins=u_co["coins"] - cr_co["cost"])
        leveled_co, new_level_co = give_card(uid, card_id_co)
        u_co2 = get_user(uid)
        cnt_co = 0
        for cid_c, cnt_c in get_user_cards(uid):
            if cid_c == card_id_co:
                cnt_co = cnt_c
        c_co = CARDS[card_id_co]
        rar_en_co = RARITY_EN.get(c_co[1], c_co[1])
        exp_co = get_card_exp(card_id_co)
        txt_co = (f"<b>👤 {esc(u_co2['nickname'])}\n"
                  f"🃏 Получена Новая Карта {esc(c_co[0])}\n\n"
                  f"♈️ Редкость: {rar_en_co}.\n"
                  f"💰 Стоимость: {c_co[3]}.\n"
                  f"💪 Сила: {c_co[2]}.\n"
                  f"🔋 Опыт: {exp_co}.\n"
                  f"📊 Шанс: {picked_co['chance']}%</b>")
        if leveled_co:
            txt_co += f"\n🔋 Новый уровень: <b>{new_level_co}</b>!"
        safe_call(bot.answer_callback_query, call.id)
        safe_call(bot.send_photo, chat_id, c_co[4], caption=txt_co)
        return

    m_case_back = re.match(r"^case:back:(\d+)$", data)
    if m_case_back:
        owner_cb = int(m_case_back.group(1))
        if uid != owner_cb:
            safe_call(bot.answer_callback_query, call.id, "⛔ Это не твоё меню.", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id)
        kb_cb = types.InlineKeyboardMarkup(row_width=1)
        for key_cb, cr_cb in CRATES.items():
            kb_cb.add(types.InlineKeyboardButton(
                f"{cr_cb['emoji']} {cr_cb['name']} — 💰 {cr_cb['cost']} монет",
                callback_data=f"case:view:{key_cb}:{uid}",
            ))
        safe_edit(chat_id, call.message.message_id,
                  "📦 <b>Кейсы</b>\nВыбери кейс:", reply_markup=kb_cb, fallback_new=True)
        return

    # ---------- trade invite ----------
    m_tinv = re.match(r"^tinvite:(accept|decline):(\d+)$", data)
    if m_tinv:
        act_ti, iid_ti = m_tinv.group(1), int(m_tinv.group(2))
        inv_ti = TRADE_INVITES.get(iid_ti)
        if not inv_ti:
            safe_call(bot.answer_callback_query, call.id, "⏳ Приглашение устарело.", show_alert=True)
            return
        if uid != inv_ti["b"]:
            safe_call(bot.answer_callback_query, call.id,
                      "⛔ Это приглашение не для тебя.", show_alert=True)
            return
        TRADE_INVITES.pop(iid_ti, None)
        a_uid = inv_ti["a"]
        b_uid = inv_ti["b"]
        fu_ti = get_user(a_uid)
        fname_ti = nick_badged(a_uid, esc(fu_ti["nickname"])) if fu_ti else str(a_uid)
        if act_ti == "decline":
            safe_call(bot.answer_callback_query, call.id, "❌ Отклонено.")
            safe_edit(chat_id, call.message.message_id,
                      f"❌ Вы отклонили обмен от игрока {fname_ti}.",
                      reply_markup=None, fallback_new=True)
            try:
                safe_call(bot.send_message, a_uid,
                          f"❌ Игрок <b>{esc(get_user(b_uid)['nickname'] if get_user(b_uid) else str(b_uid))}</b> отклонил ваш обмен.")
            except Exception:
                pass
            return
        # accept
        if user_in_trade(a_uid) or user_in_trade(b_uid):
            safe_call(bot.answer_callback_query, call.id,
                      "⚠️ Один из игроков уже в обмене.", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id, "✅ Принято! Открываю панель обмена...")
        safe_edit(chat_id, call.message.message_id,
                  f"✅ Вы приняли обмен от {fname_ti}!\nПанель обмена открыта в ЛС бота.",
                  reply_markup=None, fallback_new=True)
        tid_ti = open_new_trade_room(a_uid, b_uid)
        if not tid_ti:
            safe_call(bot.send_message, b_uid,
                      "❌ Не удалось открыть панель обмена. Убедитесь что оба запустили бота (/start).")
        return

    # ---------- trade3 (новый обмен) ----------
    if data == "trade3:noop":
        safe_call(bot.answer_callback_query, call.id)
        return

    m_t3 = re.match(r"^trade3:(coins|cards|accept|cancel|back):(\d+)$", data)
    if m_t3:
        act_t3, tid_t3 = m_t3.group(1), int(m_t3.group(2))
        room_t3 = TRADE_ROOMS.get(tid_t3)
        if not room_t3 or uid not in (room_t3["a"], room_t3["b"]) or room_t3["phase"] == "done":
            safe_call(bot.answer_callback_query, call.id, "⏳ Обмен неактивен.", show_alert=True)
            return
        other_t3 = trade_other(room_t3, uid)
        if act_t3 == "coins":
            safe_call(bot.answer_callback_query, call.id)
            u_t3 = get_user(uid)
            free_t3 = u_t3["coins"] - room_t3["offers"][uid]["coins"]
            TRADE_STATE[uid] = {"tid": tid_t3, "step": "coins", "expires": time.time() + 300}
            safe_call(bot.send_message, uid,
                      f"💰 Введите количество монет для добавления в обмен:\n"
                      f"Свободно: <b>{free_t3}$</b>\n<i>«отмена» — отменить</i>")
            return
        if act_t3 == "cards":
            safe_call(bot.answer_callback_query, call.id)
            kb_t3c = new_trade_kb_cards(tid_t3, uid)
            mid_t3 = room_t3["msgs"].get(uid)
            cid_t3 = room_t3["chats"].get(uid, uid)
            if mid_t3:
                safe_edit(cid_t3, mid_t3,
                          f"🎴 Выберите карту для добавления в обмен:",
                          reply_markup=kb_t3c, fallback_new=True)
            else:
                safe_call(bot.send_message, uid,
                          f"🎴 Выберите карту для добавления в обмен:",
                          reply_markup=kb_t3c)
            return
        if act_t3 == "accept":
            if not room_t3.get("ready"):
                room_t3["ready"] = {room_t3["a"]: False, room_t3["b"]: False}
            if room_t3["ready"].get(uid, False):
                safe_call(bot.answer_callback_query, call.id,
                          "⏳ Ты уже нажал Готов — ждём второго игрока.", show_alert=True)
                return
            room_t3["ready"][uid] = True
            other_rdy = trade_other(room_t3, uid)
            safe_call(bot.answer_callback_query, call.id, "✅ Ты готов!")
            if room_t3["ready"].get(other_rdy, False):
                ok_t3, msg_t3 = execute_trade_room(tid_t3)
                if ok_t3:
                    room_t3["phase"] = "done"
                    trade_finish_msgs(room_t3, True)
                    TRADE_ROOMS.pop(tid_t3, None)
                else:
                    room_t3["ready"][uid] = False
                    safe_call(bot.send_message, uid, f"⚠️ {msg_t3}")
                    new_trade_push(room_t3)
            else:
                new_trade_push(room_t3)
            return
        if act_t3 == "cancel":
            other_u_t3 = get_user(other_t3)
            canceller_u = get_user(uid)
            cname_t3 = esc(canceller_u["nickname"]) if canceller_u else str(uid)
            cancel_txt = f"❌ Обмен был отменен игроком <b>{cname_t3}</b>."
            for puid_t3, mid_t3 in list(room_t3["msgs"].items()):
                safe_edit(room_t3["chats"].get(puid_t3, puid_t3), mid_t3,
                          cancel_txt, reply_markup=None, fallback_new=True)
            TRADE_ROOMS.pop(tid_t3, None)
            TRADE_STATE.pop(room_t3.get("a"), None)
            TRADE_STATE.pop(room_t3.get("b"), None)
            safe_call(bot.answer_callback_query, call.id, "❌ Отменено.")
            return
        if act_t3 == "back":
            safe_call(bot.answer_callback_query, call.id)
            new_trade_push(room_t3)
            return
        return

    m_t3_addcard = re.match(r"^trade3:addcard:(\d+):(\d+)$", data)
    if m_t3_addcard:
        tid_tac, cid_tac = int(m_t3_addcard.group(1)), int(m_t3_addcard.group(2))
        room_tac = TRADE_ROOMS.get(tid_tac)
        if not room_tac or uid not in (room_tac["a"], room_tac["b"]) or room_tac["phase"] == "done":
            safe_call(bot.answer_callback_query, call.id, "⏳ Обмен неактивен.", show_alert=True)
            return
        owned_tac = card_count(uid, cid_tac)
        used_tac = room_tac["offers"][uid]["cards"].get(cid_tac, 0)
        if owned_tac - used_tac <= 0:
            safe_call(bot.answer_callback_query, call.id, "❌ Нет свободных копий.", show_alert=True)
            return
        room_tac["offers"][uid]["cards"][cid_tac] = used_tac + 1
        safe_call(bot.answer_callback_query, call.id, f"🃏 {CARDS[cid_tac][0]} добавлена!")
        # Refresh card list
        mid_tac = room_tac["msgs"].get(uid)
        cid_chat_tac = room_tac["chats"].get(uid, uid)
        if mid_tac:
            safe_edit(cid_chat_tac, mid_tac,
                      "🎴 Выберите карту для добавления в обмен:",
                      reply_markup=new_trade_kb_cards(tid_tac, uid), fallback_new=True)
        return

    m = re.match(r"^inv:(\d+)$", data)
    if m:
        _inv_mid = call.message.message_id
        _inv_owner = INV_MSG_OWNER.get(_inv_mid)
        if _inv_owner is not None and _inv_owner != uid:
            safe_call(bot.answer_callback_query, call.id,
                      "🔒 Это не твой инвентарь.\nНапиши «Инвентарь», чтобы открыть свой.", show_alert=True)
            return
        page = int(m.group(1))
        _inv_uid = _inv_owner if _inv_owner is not None else uid
        rows = get_user_cards(_inv_uid)
        if not rows:
            safe_call(bot.answer_callback_query, call.id, "Инвентарь пуст.")
            return
        kb, page, rows, per_page = kb_inventory(_inv_uid, page)
        start = page * per_page
        lines = [f"🎒 <b>Ваш Инвентарь:</b> <i>стр. {page+1}</i>\n════════════════════════════"]
        for cid, cnt in rows[start:start + per_page]:
            c = CARDS[cid]
            em = RARITY_EMOJI.get(c[1], "▫️")
            lines.append(f"{em} {esc(c[0])} — {RARITY_EN.get(c[1], c[1])} (x{cnt}) | 💪 {c[2]}")
        res = safe_edit(chat_id, call.message.message_id, "\n".join(lines), reply_markup=kb)
        if res is None:
            msg = safe_call(bot.send_message, chat_id, "\n".join(lines), reply_markup=kb)
            if msg:
                INV_PAGES[_inv_uid] = msg.message_id
                INV_MSG_OWNER[msg.message_id] = _inv_uid
        safe_call(bot.answer_callback_query, call.id)
        return

    # ---------- обмен v2 ----------
    if data == "trade2:noop":
        safe_call(bot.answer_callback_query, call.id)
        return

    m = re.match(r"^trade2:(coins|cards|clear|ready|edit|cancel|back):(\d+)$", data)
    if m:
        act, tid = m.group(1), int(m.group(2))
        room = TRADE_ROOMS.get(tid)
        if not room or uid not in (room["a"], room["b"]) or room["phase"] == "done":
            safe_call(bot.answer_callback_query, call.id, "⏳ Обмен неактивен.", show_alert=True)
            return
        other = trade_other(room, uid)
        if act == "coins":
            if room["phase"] == "confirm" or room["ready"].get(uid):
                safe_call(bot.answer_callback_query, call.id, "❌ Ты уже нажал «Готов». Нажми ✏️ Изменить.", show_alert=True)
                return
            safe_call(bot.answer_callback_query, call.id)
            u = get_user(uid)
            free = u["coins"] - room["offers"][uid]["coins"]
            TRADE_STATE[uid] = {"tid": tid, "step": "coins", "expires": time.time() + 60}
            safe_call(bot.send_message, uid,
                      f"💰 Сколько монет добавить в обмен?\nСвободно: {free}$\nНапиши числом. «отмена» — отменить.")
            return
        if act == "cards":
            if room["phase"] == "confirm" or room["ready"].get(uid):
                safe_call(bot.answer_callback_query, call.id, "❌ Ты уже нажал «Готов». Нажми ✏️ Изменить.", show_alert=True)
                return
            safe_call(bot.answer_callback_query, call.id)
            trade_set_message(room, uid, f"🃏 <b>Выбери карту для обмена #{tid}:</b>",
                              trade_kb_cards(tid, uid), source_mid=call.message.message_id)
            return
        if act == "clear":
            if room["phase"] == "confirm" or room["ready"].get(uid):
                safe_call(bot.answer_callback_query, call.id, "❌ Ты уже нажал «Готов». Нажми ✏️ Изменить.", show_alert=True)
                return
            room["offers"][uid] = {"coins": 0, "cards": {}}
            trade_reset_ready(room, uid)
            trade_push(room)
            safe_call(bot.answer_callback_query, call.id, "🗑 Вклад очищен.")
            return
        if act == "ready":
            if room["phase"] == "confirm":
                safe_call(bot.answer_callback_query, call.id, "⚠️ Оба уже готовы. Используй ✏️ Изменить.", show_alert=True)
                return
            if room["ready"].get(uid):
                safe_call(bot.answer_callback_query, call.id, "✅ Ты уже готов.")
                return
            room["ready"][uid] = True
            safe_call(bot.answer_callback_query, call.id, "✅ Ты готов!")
            if room["ready"].get(other):
                room["phase"] = "confirm"
                room["confirm"][uid] = False
                room["confirm"][other] = False
            trade_push(room)
            return
        if act == "edit":
            if room["phase"] != "confirm":
                safe_call(bot.answer_callback_query, call.id, "ℹ️ Изменять вклад можно после готовности обоих игроков.", show_alert=True)
                return
            trade_reset_ready(room, uid)
            trade_push(room)
            safe_call(bot.answer_callback_query, call.id, "✏️ Можешь менять вклад.")
            return
        if act == "cancel":
            TRADE_ROOMS.pop(tid, None)
            TRADE_STATE.pop(room["a"], None)
            TRADE_STATE.pop(room["b"], None)
            for puid, mid in list(room["msgs"].items()):
                safe_edit(room["chats"][puid], mid, f"🔄 <b>Обмен #{tid}</b>\n\n❌ Обмен отменён.", reply_markup=None, fallback_new=True)
            safe_call(bot.answer_callback_query, call.id, "❌ Отменено.")
            return
        if act == "back":
            safe_call(bot.answer_callback_query, call.id)
            trade_push(room)
            return
        return

    m = re.match(r"^trade2:addcard:(\d+):(\d+)$", data)
    if m:
        tid, cid = int(m.group(1)), int(m.group(2))
        room = TRADE_ROOMS.get(tid)
        if not room or uid not in (room["a"], room["b"]) or room["phase"] == "done":
            safe_call(bot.answer_callback_query, call.id, "⏳ Обмен неактивен.", show_alert=True)
            return
        if room["phase"] == "confirm" or room["ready"].get(uid):
            safe_call(bot.answer_callback_query, call.id, "❌ Ты уже нажал «Готов». Нажми ✏️ Изменить.", show_alert=True)
            return
        owned = card_count(uid, cid)
        used = room["offers"][uid]["cards"].get(cid, 0)
        if owned - used <= 0:
            safe_call(bot.answer_callback_query, call.id, "❌ Нет свободных копий.", show_alert=True)
            return
        room["offers"][uid]["cards"][cid] = used + 1
        trade_reset_ready(room, uid)
        trade_set_message(room, uid, f"🃏 <b>Выбери карту для обмена #{tid}:</b>",
                          trade_kb_cards(tid, uid), source_mid=call.message.message_id)
        safe_call(bot.answer_callback_query, call.id, f"🃏 {CARDS[cid][0]} +1")
        return

    m = re.match(r"^trade2:confirm:(\d+)$", data)
    if m:
        tid = int(m.group(1))
        room = TRADE_ROOMS.get(tid)
        if not room or uid not in (room["a"], room["b"]):
            safe_call(bot.answer_callback_query, call.id, "⏳ Обмен неактивен.", show_alert=True)
            return
        if room["phase"] != "confirm":
            safe_call(bot.answer_callback_query, call.id, "❌ Сначала оба должны нажать «Готов».", show_alert=True)
            return
        room["confirm"][uid] = True
        other = trade_other(room, uid)
        if room["confirm"].get(other):
            ok, resmsg = execute_trade_room(tid)
            if ok:
                room["phase"] = "done"
                trade_finish_msgs(room, True)
                TRADE_ROOMS.pop(tid, None)
                safe_call(bot.answer_callback_query, call.id, "✅ Обмен завершён!")
            else:
                trade_finish_msgs(room, False, resmsg)
                room["phase"] = "build"
                room["ready"][room["a"]] = False
                room["ready"][room["b"]] = False
                room["confirm"][room["a"]] = False
                room["confirm"][room["b"]] = False
                trade_push(room)
                safe_call(bot.answer_callback_query, call.id, "⚠️ Ошибка, обмен сброшен.", show_alert=True)
        else:
            trade_push(room)
            safe_call(bot.answer_callback_query, call.id, "✅ Ждём подтверждения второго игрока...")
        return

    # ---------- магазин ----------
    def _shop_owner_check():
        _owner = SHOP_MSG_OWNER.get(call.message.message_id)
        if _owner is not None and _owner != uid:
            safe_call(bot.answer_callback_query, call.id,
                      "🔒 Это не твой магазин.\nНапиши «Магазин», чтобы открыть свой.", show_alert=True)
            return False
        return True

    if data == "shop:back":
        if not _shop_owner_check():
            return
        safe_call(bot.answer_callback_query, call.id)
        msg = safe_edit(chat_id, call.message.message_id, txt_shop(), reply_markup=kb_shop(), fallback_new=True)
        if msg and hasattr(msg, "message_id"):
            SHOP_MSG_OWNER[msg.message_id] = uid
        return

    m = re.match(r"^shop:view:(\w+)$", data)
    if m:
        if not _shop_owner_check():
            return
        it = next((x for x in SHOP_ITEMS if x["key"] == m.group(1)), None)
        if not it:
            safe_call(bot.answer_callback_query, call.id, "❌ Товар не найден.", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id)
        safe_edit(chat_id, call.message.message_id,
                  f"👑 <b>{esc(it['name'])}</b>\n"
                  "━━━━━━━━━━━━━━━━━━━━\n"
                  f"⭐ Цена: <b>{it['price']} Звёзд Telegram</b>\n"
                  f"📋 Что даёт:\n{esc(it['desc'])}\n\n"
                  f"После оплаты привилегия активируется автоматически.",
                  reply_markup=kb_shop_item(it["key"]), fallback_new=True)
        return

    m = re.match(r"^shop:buy:(\w+)$", data)
    if m:
        if not _shop_owner_check():
            return
        it = next((x for x in SHOP_ITEMS if x["key"] == m.group(1)), None)
        safe_call(bot.answer_callback_query, call.id)
        if not it:
            safe_call(bot.send_message, chat_id, "❌ Товар не найден.")
            return
        u = get_user(uid)
        if not u:
            register_user(call.message)
            u = get_user(uid)
        nickname = u["nickname"] if u else (call.from_user.first_name or "Игрок")
        if u and u["privilege"] == it["name"]:
            safe_call(bot.send_message, chat_id, f"👑 У тебя уже есть привилегия <b>{esc(it['name'])}</b>!")
            return
        try:
            desc = it["desc"].replace("\n", " | ")[:255]
            bot.send_invoice(uid, title=f"👑 {it['name']}", description=desc,
                             invoice_payload=f"shop:{it['key']}:{uid}",
                             provider_token="", currency="XTR",
                             prices=[types.LabeledPrice(it["name"], int(it["price"]))])
            if chat_id != uid:
                safe_call(bot.send_message, chat_id,
                          f"💳 {esc(nickname)}, счёт на оплату отправлен в <b>личные сообщения</b> с ботом. Открой ЛС и нажми «Оплатить» 👇")
            else:
                safe_call(bot.send_message, uid, "💳 Счёт создан — нажми «Оплатить» ниже 👇")
        except TelegramAPIError as e:
            err = str(e).lower()
            if "bot can't initiate conversation" in err or "chat not found" in err or "forbidden" in err:
                safe_call(bot.send_message, chat_id,
                          f"❌ {esc(nickname)}, не могу написать тебе в ЛС.\nСначала запусти бота в личке командой /start, потом попробуй снова.")
            elif "stars" in err or "invoice" in err or "payment" in err:
                safe_call(bot.send_message, chat_id, "❌ Оплата через Telegram Stars не настроена.")
            else:
                safe_call(bot.send_message, chat_id, f"❌ Ошибка счёта:\n<code>{esc(str(e)[:200])}</code>")
        except Exception as e:
            safe_call(bot.send_message, chat_id, f"❌ Неожиданная ошибка:\n<code>{esc(str(e)[:200])}</code>")
        return

    # ---------- топ ----------
    def _top_owner_check():
        _owner = TOP_MSG_OWNER.get(call.message.message_id)
        if _owner is not None and _owner != uid:
            safe_call(bot.answer_callback_query, call.id,
                      "🔒 Это не твой топ.\nНапиши «Топ», чтобы открыть свой.", show_alert=True)
            return False
        return True

    if data.startswith("top:"):
        if not _top_owner_check():
            return
        kind = data.split(":", 1)[1]

        COL_MAP  = {"coins": "coins", "level": "level", "points": "points"}
        EMO_MAP  = {"coins": "💰",    "level": "🔋",    "points": "🌟"}
        NAME_MAP = {"coins": "Монетам", "level": "Уровню", "points": "Очкам"}
        if kind not in COL_MAP:
            safe_call(bot.answer_callback_query, call.id, "❌ Неизвестный тип топа.", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id)
        col = COL_MAP[kind]
        emoji = EMO_MAP[kind]
        try:
            conn = db()
            _excl = list({777000, 0} | ({BOT_ID} if BOT_ID else set()))
            _ph = ",".join("?" * len(_excl))
            rows = conn.execute(
                f"SELECT nickname, {col} AS v, user_id, level FROM users"
                f" WHERE user_id NOT IN ({_ph})"
                f" ORDER BY {col} DESC, user_id ASC LIMIT 10",
                _excl,
            ).fetchall()
            conn.close()
        except Exception as _e:
            safe_call(bot.send_message, chat_id, f"❌ Ошибка БД топа: {esc(str(_e)[:100])}")
            return
        medals = ["🥇","🥈","🥉"] + ["▫️"]*7
        lines = [f"{emoji} <b>Топ по {NAME_MAP[kind]}</b>\n════════════════════════════"]
        if not rows:
            lines.append("<i>Пока никого нет в топе.</i>")
        else:
            for i, r in enumerate(rows):
                rank_icon = get_rank(r["level"])
                if kind == "level":
                    lines.append(f"{medals[i]} {nick_badged(r['user_id'], esc(r['nickname']))} {rank_icon} — <b>Ур. {r['v']}</b>")
                else:
                    lines.append(f"{medals[i]} {nick_badged(r['user_id'], esc(r['nickname']))} {rank_icon} — <b>{r['v']}</b>")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back:topmenu"))
        txt = "\n".join(lines)
        res = safe_edit(chat_id, call.message.message_id, txt, reply_markup=kb)
        if res is None:
            new_msg = safe_call(bot.send_message, chat_id, txt, reply_markup=kb)
            if new_msg:
                TOP_MSG_OWNER[new_msg.message_id] = uid
        else:
            TOP_MSG_OWNER[call.message.message_id] = uid
        return

    if data == "back:topmenu":
        if not _top_owner_check():
            return
        safe_call(bot.answer_callback_query, call.id)
        u_bk = get_user(uid)
        nick_bk = esc(u_bk["nickname"]) if u_bk else "Игрок"
        txt_bk = f"{nick_badged(uid, nick_bk)}, выберите ниже топ который хотите открыть:"
        res = safe_edit(chat_id, call.message.message_id, txt_bk, reply_markup=kb_top_menu(), fallback_new=True)
        if res is None:
            new_msg = safe_call(bot.send_message, chat_id, txt_bk, reply_markup=kb_top_menu())
            if new_msg:
                TOP_MSG_OWNER[new_msg.message_id] = uid
        else:
            TOP_MSG_OWNER[call.message.message_id] = uid
        return

    # ---------- индекс (игроки) ----------
    if data.startswith("user:cardlist:"):
        rar = data.split(":", 2)[2]
        safe_call(bot.answer_callback_query, call.id, f"🃏 {rar}")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        ids = []
        for i, c in enumerate(CARDS):
            if c[1] == rar:
                caption = f"<b>{esc(c[0])}</b>\n♈️ {RARITY_EN.get(c[1], c[1])} | 💪 {c[2]} | 💰 {c[3]}"
                msg = safe_call(bot.send_photo, chat_id, c[4], caption=caption)
                if msg:
                    ids.append(msg.message_id)
                time.sleep(0.35)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Назад к выбору редкости", callback_data="user:cardback"))
        msg = safe_call(bot.send_message, chat_id, f"📖 <b>Индекс — {esc(rar)}</b>\nКарт: {len(ids)}", reply_markup=kb)
        if msg:
            ids.append(msg.message_id)
        CARD_VIEW[uid] = ids
        return

    if data == "user:cardback":
        safe_call(bot.answer_callback_query, call.id)
        ids = CARD_VIEW.pop(uid, [])
        for mid in ids:
            try:
                bot.delete_message(chat_id, mid)
            except Exception:
                pass
        safe_call(bot.send_message, chat_id, "📖 <b>Выберите редкость:</b>", reply_markup=kb_rarities_user())
        return

    # ---------- админ ----------
    if data == "admin:menu":
        safe_call(bot.answer_callback_query, call.id)
        safe_edit(chat_id, call.message.message_id, txt_admin_menu(), reply_markup=kb_admin_menu(), fallback_new=True)
        return

    if data == "admin:promo":
        safe_call(bot.answer_callback_query, call.id)
        safe_edit(chat_id, call.message.message_id, txt_admin_promo(), reply_markup=kb_admin_back(), fallback_new=True)
        return

    if data == "admin:stats":
        safe_call(bot.answer_callback_query, call.id)
        conn = db()
        players = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_coins = conn.execute("SELECT COALESCE(SUM(coins),0) FROM users").fetchone()[0]
        conn.close()
        safe_edit(chat_id, call.message.message_id,
                  f"📊 <b>Статистика бота:</b>\n👤 Игроков: {players}\n"
                  f"💰 Монет в игре: {total_coins}\n😶‍🌫️ Статус Бота: Активный ✅",
                  reply_markup=kb_admin_back(), fallback_new=True)
        return

    if data == "admin:broadcast":
        safe_call(bot.answer_callback_query, call.id)
        safe_edit(chat_id, call.message.message_id, txt_admin_broadcast(), reply_markup=kb_admin_back(), fallback_new=True)
        return

    if data == "admin:give":
        safe_call(bot.answer_callback_query, call.id)
        safe_edit(chat_id, call.message.message_id, txt_admin_give(), reply_markup=kb_admin_back(), fallback_new=True)
        return

    if data == "admin:cards":
        safe_call(bot.answer_callback_query, call.id)
        safe_edit(chat_id, call.message.message_id, "🃏 <b>Выберите редкость:</b>",
                  reply_markup=kb_rarities(), fallback_new=True)
        return

    if data.startswith("admin:cardlist:"):
        rar = data.split(":", 2)[2]
        safe_call(bot.answer_callback_query, call.id, f"🃏 {rar}")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        ids = []
        for i, c in enumerate(CARDS):
            if c[1] == rar:
                msg = safe_call(bot.send_photo, chat_id, c[4],
                                caption=f"<b>{esc(c[0])}</b>\n{RARITY_EN.get(c[1], c[1])} | 💪 {c[2]} | 💰 {c[3]}")
                if msg:
                    ids.append(msg.message_id)
                time.sleep(0.35)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Назад в Адм. панель", callback_data="admin:cardback"))
        msg = safe_call(bot.send_message, chat_id, f"🃏 <b>{esc(rar)}</b> — карт: {len(ids)}", reply_markup=kb)
        if msg:
            ids.append(msg.message_id)
        CARD_VIEW[uid] = ids
        return

    if data == "admin:ban":
        safe_call(bot.answer_callback_query, call.id)
        safe_call(bot.send_message, chat_id, txt_admin_ban(), reply_markup=kb_admin_back())
        return

    if data == "admin:cardback":
        safe_call(bot.answer_callback_query, call.id)
        ids = CARD_VIEW.pop(uid, [])
        for mid in ids:
            try:
                bot.delete_message(chat_id, mid)
            except Exception:
                pass
        safe_call(bot.send_message, chat_id, txt_admin_menu(), reply_markup=kb_admin_menu())
        return



    if data == "back:help":
        safe_call(bot.answer_callback_query, call.id)
        safe_edit(chat_id, call.message.message_id, txt_help(), reply_markup=None, fallback_new=True)
        return



    # ========================= БИТВА КАРТ - CALLBACKS =========================

    m_bat_mode = re.match(r"^battle:mode:(bot|pvp):(\d+)$", data)
    if m_bat_mode:
        mode_bm, owner_bm = m_bat_mode.group(1), int(m_bat_mode.group(2))
        if uid != owner_bm:
            safe_call(bot.answer_callback_query, call.id, "⛔ Это не твоя битва.", show_alert=True)
            return
        u_bm = get_user(uid)
        left_bm = battle_cd_left(u_bm)
        if left_bm > 0:
            safe_call(bot.answer_callback_query, call.id, f"⏳ Кулдаун: {fmt_time(left_bm)}", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id)
        if mode_bm == "bot":
            kb_pv = kb_battle_cards_pve(uid)
            if not kb_pv:
                safe_call(bot.send_message, chat_id, "❌ Нет карт.")
                return
            safe_call(bot.send_message, chat_id, "🃏 Выбери карту для битвы с ботом:", reply_markup=kb_pv)
        else:
            BATTLE_SELECT[uid] = {"step": "target", "chat_id": chat_id}
            safe_call(bot.send_message, chat_id,
                      "👥 Введи @username или ID игрока для вызова:\n<i>«отмена» — отменить</i>")
        return

    m_bat_pve = re.match(r"^battle:pick:pve:(\d+)$", data)
    if m_bat_pve:
        cid_pve = int(m_bat_pve.group(1))
        u_pve = get_user(uid)
        if battle_cd_left(u_pve) > 0:
            safe_call(bot.answer_callback_query, call.id, f"⏳ Кулдаун: {fmt_time(battle_cd_left(u_pve))}", show_alert=True)
            return
        if cid_pve >= len(CARDS) or cid_pve not in {c for c, _ in get_user_cards(uid)}:
            safe_call(bot.answer_callback_query, call.id, "❌ Карта не найдена.", show_alert=True)
            return
        safe_call(bot.answer_callback_query, call.id)
        safe_call(bot.send_message, chat_id, run_battle_pve(uid, cid_pve))
        return

    m_bat_inv = re.match(r"^battle:invite:(accept|decline):(\d+)$", data)
    if m_bat_inv:
        act_bi, bid_bi = m_bat_inv.group(1), int(m_bat_inv.group(2))
        room_bi = BATTLE_CHALLENGES.get(bid_bi)
        if not room_bi or room_bi.get("phase") != "invite":
            safe_call(bot.answer_callback_query, call.id, "⏳ Вызов устарел.", show_alert=True)
            return
        if uid != room_bi["b"]:
            safe_call(bot.answer_callback_query, call.id, "⛔ Это не твой вызов.", show_alert=True)
            return
        if act_bi == "decline":
            safe_call(bot.answer_callback_query, call.id, "❌ Отклонено.")
            BATTLE_CHALLENGES.pop(bid_bi, None)
            bu_d = get_user(uid)
            try:
                safe_call(bot.send_message, room_bi["a"],
                          f"❌ {esc(bu_d['nickname'] if bu_d else str(uid))} отклонил вызов.")
            except Exception:
                pass
            safe_edit(chat_id, call.message.message_id, "❌ Вы отклонили вызов.", reply_markup=None, fallback_new=True)
            return
        safe_call(bot.answer_callback_query, call.id, "✅ Вызов принят!")
        room_bi["phase"] = "pick"
        room_bi["b_chat"] = chat_id
        safe_edit(chat_id, call.message.message_id, "🃏 Выбери карту для битвы:",
                  reply_markup=kb_battle_cards_pvp(uid, bid_bi), fallback_new=True)
        bu_a = get_user(uid)
        safe_call(bot.send_message, room_bi["a_chat"],
                  f"✅ {esc(bu_a['nickname'] if bu_a else str(uid))} принял вызов! Выбери карту:",
                  reply_markup=kb_battle_cards_pvp(room_bi["a"], bid_bi))
        return

    m_bat_pvp = re.match(r"^battle:pick:pvp:(\d+):(\d+)$", data)
    if m_bat_pvp:
        bid_pp, cid_pp = int(m_bat_pvp.group(1)), int(m_bat_pvp.group(2))
        room_pp = BATTLE_CHALLENGES.get(bid_pp)
        if not room_pp or room_pp.get("phase") == "done":
            safe_call(bot.answer_callback_query, call.id, "⏳ Битва завершена.", show_alert=True)
            return
        if uid not in (room_pp["a"], room_pp["b"]):
            safe_call(bot.answer_callback_query, call.id, "⛔ Это не твоя битва.", show_alert=True)
            return
        if cid_pp >= len(CARDS) or cid_pp not in {c for c, _ in get_user_cards(uid)}:
            safe_call(bot.answer_callback_query, call.id, "❌ Карта не найдена.", show_alert=True)
            return
        key_pp = "a_card" if uid == room_pp["a"] else "b_card"
        if room_pp[key_pp] is not None:
            safe_call(bot.answer_callback_query, call.id, "✅ Ты уже выбрал карту.")
            return
        room_pp[key_pp] = cid_pp
        safe_call(bot.answer_callback_query, call.id, f"🃏 Выбрана: {CARDS[cid_pp][0]}")
        try:
            safe_call(bot.edit_message_text,
                      f"🃏 Карта выбрана: <b>{esc(CARDS[cid_pp][0])}</b>. Ждём соперника...",
                      chat_id=chat_id, message_id=call.message.message_id)
        except Exception:
            pass
        if room_pp["a_card"] is not None and room_pp["b_card"] is not None:
            finish_pvp_battle(bid_pp)
        return

    safe_call(bot.answer_callback_query, call.id, "...")


# ========================= ХЕНДЛЕРЫ =========================
@guard
def on_pre_checkout(query):
    safe_call(bot.answer_pre_checkout_query, query.id, ok=True)

@guard
def on_successful_payment(message):
    uid = message.from_user.id if message.from_user else 0
    if not uid:
        return
    sp = getattr(message, "successful_payment", None)
    payload = getattr(sp, "invoice_payload", "") if sp else ""
    m = re.match(r"^shop:(\w+):(\d+)$", payload or "")
    if not m:
        return
    key, puid = m.group(1), int(m.group(2))
    it = SHOP_ITEMS_DICT.get(key)
    if not it or puid != uid:
        safe_call(bot.send_message, uid, "⚠️ Ошибка платежа: счёт не найден. Напиши администратору.")
        return
    ensure_user_exists(uid, message.from_user.first_name or "Игрок")
    u = get_user(uid)
    if not u:
        safe_call(bot.send_message, uid, "⚠️ Ошибка профиля. Напиши /start и обратись к администратору.")
        return
    already_had = (u["privilege"] == it["name"])
    upd_user(uid, privilege=it["name"])
    priv_info = PRIVILEGES.get(it["name"], {})
    cd_min = priv_info.get("card_cd", CARD_COOLDOWN) // 60
    coin_mult = priv_info.get("coin_mult", 1)
    if already_had:
        safe_call(bot.send_message, uid,
                  f"✅ <b>Оплата прошла!</b>\n\n👑 Привилегия <b>{esc(it['name'])}</b> уже была активна — продлена/подтверждена. ❤️")
        return
    safe_call(bot.send_message, uid,
              f"✅ <b>Оплата прошла! Спасибо за поддержку! ❤️</b>\n\n"
              f"👑 Привилегия: <b>{esc(it['name'])}</b>\n"
              f"━━━━━━━━━━━━━━━━━━━━\n"
              f"{esc(it['desc'])}\n\n"
              f"⏱ Кулдаун карты: <b>{cd_min} мин</b>\n"
              f"💰 Бонус монет: <b>x{coin_mult}</b>")

@guard
def on_message(message):
    if not message.from_user:
        return
    register_chat(message)
    register_user(message)
    uid = message.from_user.id
    raw = (message.text or "").strip()
    clean = re.sub(r"^/([a-zа-яё_]+)@\S+", r"/\1", raw, flags=re.I).strip()
    if BOT_USERNAME:
        clean = re.sub(r"^@" + re.escape(BOT_USERNAME) + r"\b\s*", "", clean, flags=re.I)
    low = clean.lower()

    if uid in CARD_CREATE_STATE and low in ("отмена", "cancel"):
        CARD_CREATE_STATE.pop(uid, None)
        safe_call(bot.reply_to, message, "❌ Создание карты отменено.")
        return

    if uid in ADMIN_STATE:
        if low in ("отмена", "cancel"):
            ADMIN_STATE.pop(uid, None)
            safe_call(bot.reply_to, message, "❌ Рассылка отменена.")
            return
        st = ADMIN_STATE.pop(uid)
        safe_call(bot.reply_to, message, "📨 Рассылка запущена...")
        def _run_bc(msg=message, target=st["target"], src_uid=uid):
            try:
                ok, fail = do_broadcast(msg, target)
                safe_call(bot.send_message, src_uid, f"✅ Рассылка завершена!\n📤 Отправлено: {ok}\n❌ Ошибок: {fail}")
            except Exception as e:
                safe_call(bot.send_message, src_uid, f"⚠️ Ошибка рассылки: {esc(str(e)[:200])}")
        try:
            threading.Thread(target=_run_bc, daemon=True).start()
        except RuntimeError:
            _run_bc()
        return

    if is_admin(uid):
        if handle_admin(message, low, uid, raw=raw, clean=clean):
            return

    handle_text(message)

@guard
def on_media(message):
    if not message.from_user:
        return
    register_chat(message)
    register_user(message)
    uid = message.from_user.id
    if getattr(message, "is_automatic_forward", False):
        safe_call(bot.reply_to, message, "🎴 Напиши <b>Эксперимент</b>, чтобы получить карточку!")
        return

    if uid in CARD_CREATE_STATE:
        caption = getattr(message, "caption", "") or ""
        _ctype = getattr(message, "content_type", "")
        _ctype = getattr(_ctype, "value", _ctype)
        if _ctype != "photo" or not getattr(message, "photo", None):
            safe_call(bot.reply_to, message, "❌ Нужно фото с подписью в формате из примера. Напиши «отмена» для отмены.")
            return
        data, err = parse_card_caption(caption)
        if err:
            safe_call(bot.reply_to, message, err + "\nПопробуй ещё раз или напиши «отмена».")
            return
        CARD_CREATE_STATE.pop(uid, None)
        file_id = message.photo[-1].file_id
        safe_name = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ_\-]+", "_", data["name"]).strip("_") or "card"
        photo_path = os.path.join(CARD_PHOTOS_DIR, f"{int(time.time())}_{safe_name}.jpg")
        try:
            bot.download_photo(file_id, photo_path)
        except Exception:
            photo_path = ""
        card_id = save_custom_card(
            data["name"], data["rarity"], data["strength"], data["cost"], data["exp"],
            photo_ref=file_id, photo_path=photo_path, created_by=uid,
        )
        rar_en = RARITY_EN.get(data["rarity"], data["rarity"])
        safe_call(
            bot.reply_to, message,
            "✅ <b>Карта создана и добавлена в игру навсегда.</b>\n"
            "___________________\n"
            f"🆔 ID: {card_id}\n"
            f"🏷 Название: {esc(data['name'])}\n"
            f"♈️ Редкость: {rar_en}\n"
            f"💰 Стоимость: {data['cost']}\n"
            f"💪 Сила: {data['strength']}\n"
            f"🔋 Опыт: {data['exp']}\n"
            "___________________\n"
            "Карта уже выпадает по «Эксперимент» и сохранена в базе данных — переживёт рестарт и обновление кода.",
        )
        return

    if uid in ADMIN_STATE:
        st = ADMIN_STATE.pop(uid)
        safe_call(bot.reply_to, message, "📨 Рассылка запущена...")
        def _run_bc_media(msg=message, target=st["target"], src_uid=uid):
            try:
                ok, fail = do_broadcast(msg, target)
                safe_call(bot.send_message, src_uid, f"✅ Рассылка завершена!\n📤 Отправлено: {ok}\n❌ Ошибок: {fail}")
            except Exception as e:
                safe_call(bot.send_message, src_uid, f"⚠️ Ошибка рассылки: {esc(str(e)[:200])}")
        try:
            threading.Thread(target=_run_bc_media, daemon=True).start()
        except RuntimeError:
            _run_bc_media()
        return

def trades_gc():
    while True:
        try:
            cleanup_trades()
        except Exception:
            pass
        time.sleep(30)

def _startup_broadcast():
    for _row in get_all_chats():
        try:
            bot.send_message(_row["chat_id"], "✅ Бот запущен и готов к работе.")
        except Exception:
            pass
        time.sleep(0.40)

# ========================= ЗАПУСК =========================
dp = Dispatcher()

@dp.callback_query()
async def _aiogram_callback_handler(callback):
    await asyncio.to_thread(callback_handler, callback)

@dp.pre_checkout_query()
async def _aiogram_pre_checkout_handler(query):
    await asyncio.to_thread(on_pre_checkout, query)

@dp.message()
async def _aiogram_message_handler(message):
    if getattr(message, "successful_payment", None):
        await asyncio.to_thread(on_successful_payment, message)
        return
    content_type = getattr(message, "content_type", "")
    content_type = getattr(content_type, "value", content_type)
    if content_type in {"photo", "video", "animation", "document", "sticker", "voice"}:
        await asyncio.to_thread(on_media, message)
    else:
        await asyncio.to_thread(on_message, message)

async def _start_keepalive_server():
    from aiohttp import web as aioweb
    app_kp = aioweb.Application()
    async def health(request):
        return aioweb.Response(text="OK, bot is running")
    app_kp.router.add_get("/", health)
    runner = aioweb.AppRunner(app_kp)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = aioweb.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[NooB Bot] Keepalive HTTP-сервер слушает порт {port}")

async def _run_bot():
    global BOT_USERNAME, BOT_ID
    await _start_keepalive_server()
    bot.loop = asyncio.get_running_loop()
    print("[NooB Bot] Подключаюсь к Telegram API...")
    try:
        me = await asyncio.wait_for(bot.aiogram.get_me(), timeout=20)
    except asyncio.TimeoutError:
        print("[NooB Bot] ОШИБКА: нет ответа от Telegram API за 20с. Проверь токен/сеть.")
        raise
    BOT_USERNAME = (me.username or "").lower()
    BOT_ID = me.id
    print("[NooB Bot] Запуск v" + BOT_VERSION + " на Aiogram 3...")
    await bot.aiogram.delete_webhook(drop_pending_updates=True)
    print("[NooB Bot] Webhook удалён, polling запущен.")
    threading.Thread(target=trades_gc, daemon=True).start()
    threading.Thread(target=_startup_broadcast, daemon=True).start()
    await dp.start_polling(bot.aiogram, polling_timeout=60)

if __name__ == "__main__":
    try:
        asyncio.run(_run_bot())
    except KeyboardInterrupt:
        print("[NooB Bot] Остановлен.")
    except Exception:
        traceback.print_exc()
        raise
