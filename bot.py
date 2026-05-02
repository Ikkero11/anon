import os
import re
import logging
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Конфиг
# ─────────────────────────────────────────────
TOKEN    = os.environ['BOT_TOKEN']
ADMIN_ID = int(os.environ['ADMIN_ID'])   # ваш Telegram ID (узнать у @userinfobot)
DB_PATH  = "feedback.db"
MSK      = timezone(timedelta(hours=3))

# ─────────────────────────────────────────────
#  База данных
# ─────────────────────────────────────────────
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    with db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                username    TEXT,
                full_name   TEXT,
                category    TEXT NOT NULL,
                text        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """)

def db_create_ticket(user_id: int, username: Optional[str],
                     full_name: Optional[str], category: str, text: str) -> int:
    now = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (user_id, username, full_name, category, text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, category, text, now),
        )
        return cur.lastrowid

def db_get_ticket(ticket_id: int) -> Optional[dict]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return dict(row) if row else None

# ─────────────────────────────────────────────
#  Клавиатуры
# ─────────────────────────────────────────────
def kb_category() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧘 Антистресс-бот",                      callback_data="cat_antistress")],
        [InlineKeyboardButton(text="🎮 Игровой бот",                         callback_data="cat_game")],
        [InlineKeyboardButton(text="💡 Общее (идеи / предложения / партнёры)", callback_data="cat_general")],
    ])

def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_send"),
        InlineKeyboardButton(text="✏️ Изменить",  callback_data="cancel_send"),
    ]])

def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"),
    ]])

# ─────────────────────────────────────────────
#  FSM
# ─────────────────────────────────────────────
class FeedbackStates(StatesGroup):
    waiting_for_text = State()
    confirming       = State()

# ─────────────────────────────────────────────
#  Бот / диспетчер
# ─────────────────────────────────────────────
bot    = Bot(token=TOKEN, parse_mode="HTML")
dp     = Dispatcher(storage=MemoryStorage())
router = Router()

CATEGORY_MAP = {
    "cat_antistress": "🧘 Антистресс-бот",
    "cat_game":       "🎮 Игровой бот",
    "cat_general":    "💡 Общее (идеи / предложения / партнёры)",
}

# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Добро пожаловать в службу обратной связи!</b>\n\n"
        "🔒 <i>Все сообщения полностью анонимны.</i> Ваши данные не передаются получателю.\n\n"
        "Выберите, к кому относится ваше обращение:",
        reply_markup=kb_category(),
    )

# ─────────────────────────────────────────────
#  Выбор категории
# ─────────────────────────────────────────────
@router.callback_query(F.data.startswith("cat_"))
async def choose_category(call: CallbackQuery, state: FSMContext):
    cat_name = CATEGORY_MAP.get(call.data, "Общее")
    await state.update_data(category=cat_name)
    await state.set_state(FeedbackStates.waiting_for_text)
    await call.message.edit_text(
        f"📂 Категория: <b>{cat_name}</b>\n\n"
        "✍️ Напишите ваше сообщение — жалобу, предложение или вопрос.\n\n"
        "🔒 <i>Сообщение анонимно. Отправитель не раскрывается.</i>",
        reply_markup=kb_cancel(),
    )
    await call.answer()

# ─────────────────────────────────────────────
#  Получение текста
# ─────────────────────────────────────────────
@router.message(FeedbackStates.waiting_for_text)
async def receive_text(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Пожалуйста, отправьте текстовое сообщение.")
        return
    await state.update_data(text=message.text)
    data = await state.get_data()
    await message.answer(
        f"📋 <b>Проверьте ваше сообщение перед отправкой:</b>\n\n"
        f"📂 Категория: <b>{data['category']}</b>\n\n"
        f"💬 Текст:\n<i>{message.text}</i>\n\n"
        "Отправить?",
        reply_markup=kb_confirm(),
    )
    await state.set_state(FeedbackStates.confirming)

# ─────────────────────────────────────────────
#  Подтверждение отправки
# ─────────────────────────────────────────────
@router.callback_query(FeedbackStates.confirming, F.data == "confirm_send")
async def confirm_send(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = call.from_user

    ticket_id = db_create_ticket(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        category=data["category"],
        text=data["text"],
    )

    now_msk          = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
    username_display = f"@{user.username}" if user.username else "—"

    # → Администратору
    await bot.send_message(
        ADMIN_ID,
        f"📩 <b>Новое обращение #{ticket_id}</b>\n"
        f"{'─' * 32}\n"
        f"📂 <b>Категория:</b> {data['category']}\n"
        f"🆔 <b>Тикет:</b> #{ticket_id}\n"
        f"👤 <b>Пользователь:</b> {username_display} | <code>{user.id}</code>\n"
        f"📅 <b>Дата и время:</b> {now_msk}\n"
        f"{'─' * 32}\n"
        f"💬 <b>Текст сообщения:</b>\n\n{data['text']}",
    )

    # → Пользователю
    await call.message.edit_text(
        f"✅ <b>Сообщение отправлено!</b>\n\n"
        f"🎫 Ваш номер тикета: <b>#{ticket_id}</b>\n\n"
        "Если мы ответим на ваше обращение — вы получите уведомление прямо здесь.\n\n"
        "🔒 <i>Напоминаем: всё анонимно.</i>",
    )
    await state.clear()
    await call.answer("Отправлено!")

# ─────────────────────────────────────────────
#  Отмена
# ─────────────────────────────────────────────
@router.callback_query(F.data.in_({"cancel_action", "cancel_send"}))
async def cancel_action(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Отменено. Нажмите /start чтобы начать заново.")
    await call.answer()

# ─────────────────────────────────────────────
#  Ответ администратора → пользователю
# ─────────────────────────────────────────────
@router.message(F.reply_to_message, F.from_user.id == ADMIN_ID)
async def admin_reply(message: Message):
    original = message.reply_to_message
    if not original or not original.text:
        return

    match = re.search(r"#(\d+)", original.text)
    if not match:
        await message.answer("⚠️ Не удалось найти номер тикета в исходном сообщении.")
        return

    ticket_id = int(match.group(1))
    ticket    = db_get_ticket(ticket_id)
    if not ticket:
        await message.answer(f"⚠️ Тикет #{ticket_id} не найден в базе данных.")
        return

    now_msk = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")

    try:
        await bot.send_message(
            ticket["user_id"],
            f"📬 <b>Ответ на ваше обращение</b>\n"
            f"{'─' * 32}\n"
            f"🎫 <b>Тикет:</b> #{ticket_id}\n"
            f"📂 <b>Категория:</b> {ticket['category']}\n"
            f"📅 <b>Дата ответа:</b> {now_msk}\n"
            f"{'─' * 32}\n\n"
            f"💬 <b>Ваше сообщение:</b>\n<i>{ticket['text']}</i>\n\n"
            f"{'─' * 32}\n\n"
            f"✉️ <b>Ответ:</b>\n\n{message.text}",
        )
        await message.answer(f"✅ Ответ отправлен пользователю по тикету #{ticket_id}.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ: {e}")

# ─────────────────────────────────────────────
#  Запуск
# ─────────────────────────────────────────────
async def main():
    db_init()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
