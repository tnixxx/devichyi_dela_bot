import asyncio
import logging
from datetime import datetime, timedelta, date, time
import calendar
import uuid
import os
from io import BytesIO

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, InputMediaPhoto, LabeledPrice,
    PreCheckoutQuery, SuccessfulPayment
)

from database import create_pool
from dotenv import load_dotenv
from icalendar import Calendar, Event, Alarm
from locales import TEXTS

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, request_timeout=60)
dp = Dispatcher()
dp['db_pool'] = None

# ---------- Константы ----------
WORK_START_HOUR = 6
WORK_END_HOUR = 22
SLOT_DURATION = 1

DEFAULT_IMAGE = "AgACAgIAAxkBAAOuadflHkMQHyFsQ8yls6F2PoVrRd8AAnEQaxsJS8BKzjU4E0_lknIBAAMCAAN4AAM7BA"
PUBLIC_URL = "https://ваш-домен.ngrok.io"   # замените на ваш реальный URL

# ---------- Список категорий ----------
CATEGORIES = [
    {"id": "couch", "name": "🛏 Кушетки", "emoji": "🛏"},
    {"id": "hairdresser", "name": "💇‍♀️ Парикмахерские места", "emoji": "💇‍♀️"},
    {"id": "dressing", "name": "🎭 Гримерки", "emoji": "🎭"}
]

# ---------- Список месяцев и годов ----------
MONTHS = [
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"
]
CURRENT_YEAR = datetime.now().year
YEARS = list(range(CURRENT_YEAR - 1, CURRENT_YEAR + 5))

# ---------- FSM состояния ----------
class BookingStates(StatesGroup):
    choosing_category = State()
    browsing_workspace_detail = State()
    choosing_rental_type = State()
    choosing_date = State()
    choosing_time_slot = State()
    choosing_duration = State()
    choosing_start_date = State()
    choosing_end_date = State()
    confirming = State()
    choosing_month = State()
    choosing_year = State()
    waiting_for_payment = State()
    choosing_reminder_type = State()
    choosing_reminder_time = State()

# ---------- Вспомогательные функции для локализации ----------
def get_text(key, lang='ru', **kwargs):
    value = TEXTS.get(lang, TEXTS['ru']).get(key, key)
    if kwargs and isinstance(value, str):
        value = value.format(**kwargs)
    return value

async def get_user_language(user_id):
    if user_id < 0:   # вручную добавленные мастера
        return 'ru'
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        lang = await conn.fetchval("SELECT language FROM masters WHERE telegram_id = $1", user_id)
        return lang if lang else 'ru'
    
def get_workspace_name(original_name: str, lang: str) -> str:
    workspaces_dict = TEXTS.get(lang, {}).get('workspaces', {})
    return workspaces_dict.get(original_name, original_name)

# ---------- Клавиатура главного меню ----------
def main_menu_keyboard(lang='ru'):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('book_btn', lang), callback_data="main_book", style="primary")],
        [InlineKeyboardButton(text=get_text('about_btn', lang), callback_data="main_about")],
        [InlineKeyboardButton(text=get_text('lang_btn', lang), callback_data="main_lang")]
    ])

# ---------- Запуск / остановка ----------
@dp.startup()
async def on_startup():
    dp['db_pool'] = await create_pool()
    asyncio.create_task(cleanup_expired_pending())
    asyncio.create_task(auto_complete_bookings())
    asyncio.create_task(start_web_server())
    logging.info("Бот запущен, пул БД создан, фоновые задачи запущены")

@dp.shutdown()
async def on_shutdown():
    if dp['db_pool']:
        await dp['db_pool'].close()
    logging.info("Бот остановлен")

async def start_web_server():
    app = web.Application()
    app.router.add_static('/static', 'static')
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logging.info("Веб-сервер запущен на порту 8080")

async def cleanup_expired_pending():
    while True:
        await asyncio.sleep(60)
        pool = dp['db_pool']
        if not pool:
            continue
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM bookings WHERE status = 'pending' AND created_at < now() - interval '2 minutes'")
            logging.info("Очистка устаревших pending-броней выполнена")

async def auto_complete_bookings():
    while True:
        await asyncio.sleep(600)
        pool = dp['db_pool']
        if not pool:
            continue
        async with pool.acquire() as conn:
            await conn.execute("UPDATE bookings SET status = 'completed' WHERE status = 'paid' AND end_time < now()")
            logging.info("Автозавершение completed-броней выполнено")

@dp.callback_query(BookingStates.choosing_end_date, lambda c: c.data.startswith("date_") and not c.data.startswith("past_date_"))
async def process_end_date(callback: CallbackQuery, state: FSMContext):
    # Проверяем, что мы в нужном состоянии
    current_state = await state.get_state()
    if current_state != BookingStates.choosing_end_date:
        logging.warning(f"process_end_date called in wrong state: {current_state}")
        # Можно попробовать принудительно перейти в нужное состояние
        await state.set_state(BookingStates.choosing_end_date)
    date_str = callback.data.split("_")[1]
    end_date = datetime.fromisoformat(date_str).date()
    await state.update_data(end_date=end_date)
    data = await state.get_data()
    start_date = data['start_date']
    if end_date < start_date:
        lang = await get_user_language(callback.from_user.id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text('back_to_start_date', lang), callback_data="back_to_start_date")]
        ])
        await callback.message.edit_text(get_text('end_date_before_start', lang), reply_markup=kb)
        await callback.answer()
        return
    await check_multiday_availability(callback.message.chat.id, state, callback.from_user.id)
    await callback.answer()

# ---------- Команда /start ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    lang = await get_user_language(message.from_user.id)
    await message.answer(get_text('welcome', lang))
    await message.answer_photo(
        photo=DEFAULT_IMAGE,
        caption=get_text('main_menu_caption', lang),
        reply_markup=main_menu_keyboard(lang)
    )

# ---------- Команда /dbcheck ----------
@dp.message(Command("dbcheck"))
async def cmd_dbcheck(message: types.Message):
    pool = dp['db_pool']
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        await message.answer("✅ Подключение к базе данных работает!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ---------- Обработчик "О коворкинге" ----------
@dp.callback_query(lambda c: c.data == "main_about")
async def about_coworking(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('back_btn', lang), callback_data="back_to_main")]
    ])
    await callback.message.edit_caption(caption=get_text('about_text', lang), reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# ---------- Обработчик языка ----------
@dp.callback_query(lambda c: c.data == "main_lang")
async def language_menu(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('lang_ru', lang), callback_data="lang_ru")],
        [InlineKeyboardButton(text=get_text('lang_en', lang), callback_data="lang_en")],
        [InlineKeyboardButton(text=get_text('back_btn', lang), callback_data="back_to_main")]
    ])
    await callback.message.edit_caption(caption=get_text('choose_language', lang), reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("lang_"))
async def set_language(callback: CallbackQuery, state: FSMContext):
    new_lang = callback.data.split("_")[1]
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        await conn.execute("UPDATE masters SET language = $1 WHERE telegram_id = $2", new_lang, callback.from_user.id)
    text = get_text('lang_changed', new_lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('back_btn', new_lang), callback_data="back_to_main")]
    ])
    await callback.message.edit_caption(caption=text, reply_markup=kb)
    await callback.answer()

# ---------- Возврат в главное меню (из разделов "О коворкинге" и "Язык") ----------
@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_edit(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.clear()
    await callback.message.edit_caption(
        caption=get_text('main_menu_caption', lang),
        reply_markup=main_menu_keyboard(lang)
    )
    await callback.answer()

# ---------- Начало бронирования ----------
@dp.callback_query(lambda c: c.data == "main_book")
async def start_booking(callback: CallbackQuery, state: FSMContext):
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        blocked = await conn.fetchval("SELECT is_blocked FROM masters WHERE telegram_id = $1", callback.from_user.id)
        if blocked:
            lang = await get_user_language(callback.from_user.id)
            await callback.answer(get_text('blocked_message', lang), show_alert=True)
            return
    await callback.message.delete()
    await state.update_data(category_index=0)
    await show_category_album(callback.message.chat.id, state, callback.from_user.id)
    await state.set_state(BookingStates.choosing_category)
    await callback.answer()

# ---------- Показ категорий (альбом из фото) ----------
async def show_category_album(chat_id: int, state: FSMContext, user_id: int):
    lang = await get_user_language(user_id)
    data = await state.get_data()
    # Удаляем старые сообщения
    for key in ['album_msg_ids', 'detail_album_msg_ids']:
        for msg_id in data.get(key, []):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except:
                pass
    for key in ['control_msg_id', 'detail_control_msg_id']:
        msg_id = data.get(key)
        if msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except:
                pass

    idx = data.get('category_index', 0) % len(CATEGORIES)
    await state.update_data(category_index=idx)
    category = CATEGORIES[idx]

    pool = dp['db_pool']
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT id, name, image_url_1 FROM workspaces WHERE category = $1 ORDER BY id",
            category['id']
        )
    if not rows:
        await bot.send_message(chat_id, get_text('no_workspaces', lang))
        await state.clear()
        return

    media_group = []
    workspaces_info = []
    for row in rows:
        img_url = row['image_url_1'] if row['image_url_1'] else DEFAULT_IMAGE
        media_group.append(InputMediaPhoto(media=img_url))
        workspaces_info.append({"id": row['id'], "name": row['name']})
    album_msgs = await bot.send_media_group(chat_id, media=media_group)
    album_msg_ids = [msg.message_id for msg in album_msgs]

    nav_buttons = [
        InlineKeyboardButton(text=get_text('prev_category', lang), callback_data="cat_prev"),
        InlineKeyboardButton(text=get_text('next_category', lang), callback_data="cat_next")
    ]
    ws_rows = [[InlineKeyboardButton(text=get_workspace_name(ws['name'], lang), callback_data=f"ws_select_{ws['id']}")] for ws in workspaces_info]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav_buttons,
        *ws_rows,
        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
    ])
    control_msg = await bot.send_message(chat_id, get_text('select_workspace', lang), reply_markup=kb)

    await state.update_data(
        album_msg_ids=album_msg_ids,
        control_msg_id=control_msg.message_id,
        current_category=category['id'],
        workspaces_list=workspaces_info
    )

@dp.callback_query(BookingStates.choosing_category, lambda c: c.data in ("cat_prev", "cat_next"))
async def navigate_categories(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = data.get('category_index', 0)
    total = len(CATEGORIES)
    if callback.data == "cat_prev":
        idx = (idx - 1) % total
    else:
        idx = (idx + 1) % total
    await state.update_data(category_index=idx)
    await show_category_album(callback.message.chat.id, state, callback.from_user.id)
    try:
        await callback.answer()
    except:
        pass

@dp.callback_query(BookingStates.choosing_category, lambda c: c.data.startswith("ws_select_"))
async def select_workspace_from_list(callback: CallbackQuery, state: FSMContext):
    workspace_id = int(callback.data.split("_")[2])
    await state.update_data(selected_workspace_id=workspace_id)
    data = await state.get_data()
    for msg_id in data.get('album_msg_ids', []):
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
        except:
            pass
    if data.get('control_msg_id'):
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=data['control_msg_id'])
        except:
            pass
    await show_workspace_detail(callback.message.chat.id, state, callback.from_user.id)
    await state.set_state(BookingStates.browsing_workspace_detail)
    try:
        await callback.answer()
    except:
        pass

# ---------- Детальный просмотр места ----------
async def show_workspace_detail(chat_id: int, state: FSMContext, user_id: int):
    lang = await get_user_language(user_id)
    data = await state.get_data()
    # Удаляем предыдущие детальные альбомы и сообщения
    for msg_id in data.get('detail_album_msg_ids', []):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except:
            pass
    if data.get('detail_control_msg_id'):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=data['detail_control_msg_id'])
        except:
            pass

    workspace_id = data['selected_workspace_id']
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, description, price_per_hour, price_per_day, price_per_multi_day, "
            "image_url_1, image_url_2, image_url_3 FROM workspaces WHERE id = $1",
            workspace_id
        )
    if not row:
        await bot.send_message(chat_id, get_text('workspace_not_found', lang))
        await state.clear()
        return

    ws = dict(row)
    await state.update_data(selected_workspace=ws)

    media_group = []
    for i in range(1, 4):
        img_id = ws.get(f'image_url_{i}')
        if not img_id:
            img_id = DEFAULT_IMAGE
        media_group.append(InputMediaPhoto(media=img_id))
    album_msgs = await bot.send_media_group(chat_id, media=media_group)
    detail_album_msg_ids = [msg.message_id for msg in album_msgs]

    # Локализованное название места
    localized_name = get_workspace_name(ws['name'], lang)

    caption = (
        f"🪑 <b>{localized_name}</b>\n"
        f"{ws['description']}\n\n"
        f"💰 {get_text('price_per_hour', lang)}: {ws['price_per_hour']} руб/час\n"
        f"💰 {get_text('price_per_day', lang)}: {ws['price_per_day']} руб\n"
        f"💰 {get_text('price_per_multi_day', lang)}: {ws['price_per_multi_day']} руб/сутки"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('hourly', lang), callback_data="rent_hourly", style="primary")],
        [InlineKeyboardButton(text=get_text('daily', lang), callback_data="rent_daily")],
        [InlineKeyboardButton(text=get_text('multiday', lang), callback_data="rent_multiday")],
        [InlineKeyboardButton(text=get_text('back_to_categories', lang), callback_data="back_to_categories")],
        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
    ])
    control_msg = await bot.send_message(chat_id, get_text('choose_rental_type', lang), reply_markup=kb)

    await state.update_data(
        detail_album_msg_ids=detail_album_msg_ids,
        detail_control_msg_id=control_msg.message_id
    )
    
@dp.callback_query(BookingStates.browsing_workspace_detail, lambda c: c.data == "back_to_categories")
async def back_to_categories_from_detail(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    for msg_id in data.get('detail_album_msg_ids', []):
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
        except:
            pass
    if data.get('detail_control_msg_id'):
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=data['detail_control_msg_id'])
        except:
            pass
    await show_category_album(callback.message.chat.id, state, callback.from_user.id)
    await state.set_state(BookingStates.choosing_category)
    try:
        await callback.answer()
    except:
        pass

@dp.callback_query(BookingStates.browsing_workspace_detail, lambda c: c.data.startswith("rent_"))
async def choose_rental_type_from_detail(callback: CallbackQuery, state: FSMContext):
    rent_type = callback.data.split("_")[1]  # 'hourly', 'daily', 'multiday'
    await state.update_data(rent_type=rent_type)
    data = await state.get_data()
    control_msg_id = data['detail_control_msg_id']
    await state.update_data(dynamic_msg_id=control_msg_id)
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if rent_type in ("hourly", "daily"):
        await ask_date(user_id, chat_id, state, control_msg_id=control_msg_id)
        await state.set_state(BookingStates.choosing_date)
    elif rent_type == "multiday":
        await ask_date(user_id, chat_id, state, for_start=True, control_msg_id=control_msg_id)
        await state.set_state(BookingStates.choosing_start_date)
    else:
        await callback.answer("Неизвестный тип аренды", show_alert=True)
        return
    await callback.answer()

# ---------- Календарь (выбор даты) ----------
def get_month_keyboard(lang='ru'):
    months_local = get_text('months', lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for i, month in enumerate(months_local):
        row.append(InlineKeyboardButton(text=month, callback_data=f"month_{i+1}"))
        if len(row) == 3:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('back_to_rent_type', lang), callback_data="back_to_rent_type")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")])
    return kb

def get_year_keyboard(lang='ru'):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for year in YEARS:
        row.append(InlineKeyboardButton(text=str(year), callback_data=f"year_{year}"))
        if len(row) == 4:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('back_to_month_selection', lang), callback_data="back_to_month_selection")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")])
    return kb

def get_calendar_keyboard(year: int, month: int, prefix: str = "date", lang: str = 'ru'):
    cal = calendar.monthcalendar(year, month)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    months_local = get_text('months', lang)
    title = f"{months_local[month-1]} {year}"
    nav_row = [
        InlineKeyboardButton(text="◀️", callback_data=f"cal_prev_{year}_{month}"),
        InlineKeyboardButton(text=title, callback_data="choose_month_year"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_next_{year}_{month}")
    ]
    kb.inline_keyboard.append(nav_row)
    weekdays = get_text('weekdays_short', lang)
    kb.inline_keyboard.append([InlineKeyboardButton(text=day, callback_data=f"weekday_{i}") for i, day in enumerate(weekdays)])
    today = datetime.now().date()
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="empty_day"))
            else:
                date_obj = date(year, month, day)
                if date_obj < today:
                    row.append(InlineKeyboardButton(text=str(day), callback_data=f"past_date_{date_obj.isoformat()}"))
                else:
                    callback_data = f"{prefix}_{date_obj.isoformat()}"
                    row.append(InlineKeyboardButton(text=str(day), callback_data=callback_data))
        kb.inline_keyboard.append(row)
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('back_to_rent_type', lang), callback_data="back_to_rent_type_from_calendar")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")])
    return kb

async def show_calendar(user_id: int, chat_id: int, state: FSMContext, year: int, month: int, for_start: bool, control_msg_id: int):
    lang = await get_user_language(user_id)
    prefix = "start_date" if for_start else "date"
    kb = get_calendar_keyboard(year, month, prefix, lang)
    text = get_text('choose_date', lang) if not for_start else get_text('choose_start_date', lang)
    await state.update_data(calendar_year=year, calendar_month=month, calendar_for_start=for_start)
    try:
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=control_msg_id, reply_markup=kb)
    except Exception as e:
        if "message is not modified" in str(e):
            # Ничего не делаем, сообщение уже корректно
            pass
        elif "message to edit not found" in str(e):
            # Сообщение исчезло – отправим новое
            new_msg = await bot.send_message(chat_id, text, reply_markup=kb)
            await state.update_data(dynamic_msg_id=new_msg.message_id)
            if for_start:
                await state.update_data(detail_control_msg_id=new_msg.message_id)
            else:
                await state.update_data(control_msg_id=new_msg.message_id)
        else:
            raise

async def ask_date(user_id: int, chat_id: int, state: FSMContext, for_start=False, control_msg_id=None, year=None, month=None):
    if control_msg_id is None:
        data = await state.get_data()
        control_msg_id = data.get('dynamic_msg_id')
    if year is None or month is None:
        today = datetime.now().date()
        year = today.year
        month = today.month
    await show_calendar(user_id, chat_id, state, year, month, for_start, control_msg_id)

    
@dp.callback_query(BookingStates.choosing_date, lambda c: c.data.startswith("cal_prev_") or c.data.startswith("cal_next_"))
@dp.callback_query(BookingStates.choosing_start_date, lambda c: c.data.startswith("cal_prev_") or c.data.startswith("cal_next_"))
@dp.callback_query(BookingStates.choosing_end_date, lambda c: c.data.startswith("cal_prev_") or c.data.startswith("cal_next_"))
async def calendar_navigation(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    action = parts[1]
    year = int(parts[2])
    month = int(parts[3])
    if action == "prev":
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    else:
        month += 1
        if month > 12:
            month = 1
            year += 1
    data = await state.get_data()
    for_start = data.get('calendar_for_start', False)
    control_msg_id = data.get('dynamic_msg_id')
    await show_calendar(callback.from_user.id, callback.message.chat.id, state, year, month, for_start, control_msg_id)
    try:
        await callback.answer()
    except:
        pass

@dp.callback_query(lambda c: c.data.startswith("start_date_") and not c.data.startswith("past_date_"))
async def process_start_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[2]
    start_date = datetime.fromisoformat(date_str).date()
    await state.update_data(start_date=start_date)
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    await ask_date(user_id, chat_id, state, for_start=False, year=start_date.year, month=start_date.month)
    await state.set_state(BookingStates.choosing_end_date)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "choose_month_year")
async def choose_month_year(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    for_start = data.get('calendar_for_start', False)
    await state.update_data(calendar_for_start=for_start)
    await state.set_state(BookingStates.choosing_month)
    lang = await get_user_language(callback.from_user.id)
    kb = get_month_keyboard(lang)
    control_msg_id = data.get('dynamic_msg_id')
    await bot.edit_message_text(text=get_text('choose_month', lang), chat_id=callback.message.chat.id, message_id=control_msg_id, reply_markup=kb)
    await callback.answer()

@dp.callback_query(BookingStates.choosing_month, lambda c: c.data.startswith("month_"))
async def process_month_selection(callback: CallbackQuery, state: FSMContext):
    month = int(callback.data.split("_")[1])
    await state.update_data(selected_month=month)
    await state.set_state(BookingStates.choosing_year)
    lang = await get_user_language(callback.from_user.id)
    kb = get_year_keyboard(lang)
    data = await state.get_data()
    control_msg_id = data.get('dynamic_msg_id')
    await bot.edit_message_text(text=get_text('choose_year', lang), chat_id=callback.message.chat.id, message_id=control_msg_id, reply_markup=kb)
    await callback.answer()

@dp.callback_query(BookingStates.choosing_year, lambda c: c.data.startswith("year_"))
async def process_year_selection(callback: CallbackQuery, state: FSMContext):
    year = int(callback.data.split("_")[1])
    data = await state.get_data()
    month = data.get('selected_month', datetime.now().month)
    for_start = data.get('calendar_for_start', False)
    control_msg_id = data.get('dynamic_msg_id')
    await state.set_state(BookingStates.choosing_date if not for_start else BookingStates.choosing_start_date)
    await show_calendar(callback.from_user.id, callback.message.chat.id, state, year, month, for_start, control_msg_id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_date_selection")
async def back_to_date_selection(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    for_start = data.get('calendar_for_start', False)
    control_msg_id = data.get('dynamic_msg_id')
    await state.set_state(BookingStates.choosing_date if not for_start else BookingStates.choosing_start_date)
    year = data.get('calendar_year', datetime.now().year)
    month = data.get('calendar_month', datetime.now().month)
    await show_calendar(callback.from_user.id, callback.message.chat.id, state, year, month, for_start, control_msg_id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_month_selection")
async def back_to_month_selection(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingStates.choosing_month)
    lang = await get_user_language(callback.from_user.id)
    kb = get_month_keyboard(lang)
    data = await state.get_data()
    control_msg_id = data.get('dynamic_msg_id')
    await bot.edit_message_text(text=get_text('choose_month', lang), chat_id=callback.message.chat.id, message_id=control_msg_id, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_rent_type")
async def back_to_rent_type_from_date(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # Пытаемся получить ID сообщения для редактирования, если нет – будем отправлять новое
    control_msg_id = data.get('detail_control_msg_id') or data.get('dynamic_msg_id')
    lang = await get_user_language(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('hourly', lang), callback_data="rent_hourly", style="primary")],
        [InlineKeyboardButton(text=get_text('daily', lang), callback_data="rent_daily")],
        [InlineKeyboardButton(text=get_text('multiday', lang), callback_data="rent_multiday")],
        [InlineKeyboardButton(text=get_text('back_to_categories', lang), callback_data="back_to_categories")],
        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
    ])
    
    if control_msg_id:
        try:
            await bot.edit_message_text(
                text=get_text('choose_rental_type', lang),
                chat_id=callback.message.chat.id,
                message_id=control_msg_id,
                reply_markup=kb
            )
        except Exception as e:
            logging.warning(f"Не удалось отредактировать сообщение {control_msg_id}: {e}")
            control_msg_id = None
    if not control_msg_id:
        # Отправляем новое сообщение
        new_msg = await callback.message.answer(
            get_text('choose_rental_type', lang),
            reply_markup=kb
        )
        await state.update_data(detail_control_msg_id=new_msg.message_id)
    
    await state.set_state(BookingStates.browsing_workspace_detail)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_rent_type_from_calendar")
async def back_to_rent_type_from_calendar(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('hourly', lang), callback_data="rent_hourly", style="primary")],
        [InlineKeyboardButton(text=get_text('daily', lang), callback_data="rent_daily")],
        [InlineKeyboardButton(text=get_text('multiday', lang), callback_data="rent_multiday")],
        [InlineKeyboardButton(text=get_text('back_to_categories', lang), callback_data="back_to_categories")],
        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
    ])
    # Редактируем текущее сообщение (календарь) на выбор типа аренды
    await callback.message.edit_text(
        text=get_text('choose_rental_type', lang),
        reply_markup=kb
    )
    await state.set_state(BookingStates.browsing_workspace_detail)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "empty_day")
async def empty_day_handler(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    await callback.answer(get_text('choose_concrete_date', lang), show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("weekday_"))
async def weekday_handler(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    await callback.answer(get_text('choose_concrete_date', lang), show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("past_date_"))
async def past_date_handler(callback: CallbackQuery):
    await callback.answer("Забронировать дату, которая уже прошла, не получится", show_alert=True)


# ---------- Выбор даты для почасовой/дневной ----------
@dp.callback_query(BookingStates.choosing_date, lambda c: c.data.startswith("date_") and not c.data.startswith("past_date_"))
async def process_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    selected_date = datetime.fromisoformat(date_str).date()
    await state.update_data(selected_date=selected_date)
    data = await state.get_data()
    rent_type = data['rent_type']
    if rent_type == "hourly":
        await show_available_slots(callback.message.chat.id, state, callback.from_user.id)
        await state.set_state(BookingStates.choosing_time_slot)
    else:
        await check_daily_availability(callback.message.chat.id, state, callback.from_user.id)
    try:
        await callback.answer()
    except:
        pass

# ---------- Почасовая аренда ----------
async def show_available_slots(chat_id: int, state: FSMContext, user_id: int):
    lang = await get_user_language(user_id)
    data = await state.get_data()
    workspace_id = data['selected_workspace']['id']
    selected_date = data['selected_date']
    pool = dp['db_pool']
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    slots = []
    async with pool.acquire() as conn:
        for hour in range(WORK_START_HOUR, WORK_END_HOUR):
            slot_start = datetime.combine(selected_date, time(hour, 0))
            slot_end = slot_start + timedelta(hours=1)
            conflicting = await conn.fetchval("""
                SELECT 1 FROM bookings
                WHERE workspace_id = $1
                  AND status IN ('pending', 'paid')
                  AND tstzrange(start_time, end_time) && tstzrange($2, $3)
                LIMIT 1
            """, workspace_id, slot_start, slot_end)
            if not conflicting:
                btn_text = f"{hour:02d}:00"
                callback_data = f"slot_{slot_start.isoformat()}"
                kb.inline_keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=callback_data)])
                slots.append(slot_start)
    if not kb.inline_keyboard:
        text = get_text('no_free_hours', lang)
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text('back_to_date', lang), callback_data="back_to_date")],
            [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
        ])
        control_msg_id = data.get('dynamic_msg_id')
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=control_msg_id, reply_markup=back_kb)
        return
    text = get_text('choose_start_time', lang).format(selected_date.strftime('%d.%m.%Y'))
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('back_to_date', lang), callback_data="back_to_date")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")])
    control_msg_id = data.get('dynamic_msg_id')
    await bot.edit_message_text(text=text, chat_id=chat_id, message_id=control_msg_id, reply_markup=kb)
    await state.update_data(slots=slots)

@dp.callback_query(BookingStates.choosing_time_slot, lambda c: c.data.startswith("slot_"))
async def process_time_slot(callback: CallbackQuery, state: FSMContext):
    start_iso = callback.data.split("_")[1]
    start_time = datetime.fromisoformat(start_iso)
    await state.update_data(selected_start_time=start_time)
    data = await state.get_data()
    workspace_id = data['selected_workspace']['id']
    pool = dp['db_pool']
    max_hours = 0
    async with pool.acquire() as conn:
        for h in range(1, 24 - start_time.hour + 1):
            end_time = start_time + timedelta(hours=h)
            if end_time.time() > time(WORK_END_HOUR, 0):
                break
            conflicting = await conn.fetchval("""
                SELECT 1 FROM bookings
                WHERE workspace_id = $1
                  AND status IN ('pending', 'paid')
                  AND tstzrange(start_time, end_time) && tstzrange($2, $3)
                LIMIT 1
            """, workspace_id, start_time, end_time)
            if conflicting:
                break
            max_hours = h
    if max_hours == 0:
        lang = await get_user_language(callback.from_user.id)
        await callback.answer(get_text('slot_already_taken', lang), show_alert=True)
        return
    duration_buttons = []
    for h in range(1, max_hours + 1):
        duration_buttons.append([InlineKeyboardButton(text=f"{h} час", callback_data=f"duration_{h}")])
    kb = InlineKeyboardMarkup(inline_keyboard=duration_buttons + [
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_slots")],
        [InlineKeyboardButton(text=get_text('main_menu_btn', 'ru'), callback_data="back_to_main_from_booking")]
    ])
    await callback.message.edit_text(text=f"Вы выбрали начало в {start_time.strftime('%H:%M')}. Укажите длительность:", reply_markup=kb)
    await state.set_state(BookingStates.choosing_duration)
    await callback.answer()

@dp.callback_query(BookingStates.choosing_duration, lambda c: c.data.startswith("duration_"))
async def process_duration(callback: CallbackQuery, state: FSMContext):
    hours = int(callback.data.split("_")[1])
    data = await state.get_data()
    start_time = data['selected_start_time']
    end_time = start_time + timedelta(hours=hours)
    await state.update_data(start_time=start_time, end_time=end_time)
    await confirm_booking(callback.message.chat.id, state, callback.from_user.id)
    await callback.answer()

@dp.callback_query(BookingStates.choosing_duration, lambda c: c.data == "back_to_slots")
async def back_to_slots(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingStates.choosing_time_slot)
    data = await state.get_data()
    selected_date = data['selected_date']
    slots = data.get('slots', [])
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for slot in slots:
        kb.inline_keyboard.append([InlineKeyboardButton(text=slot.strftime("%H:%M"), callback_data=f"slot_{slot.isoformat()}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ К выбору даты", callback_data="back_to_date")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=get_text('main_menu_btn', 'ru'), callback_data="back_to_main_from_booking")])
    await callback.message.edit_text(text=f"Выберите время начала для {selected_date.strftime('%d.%m.%Y')}:", reply_markup=kb)
    await callback.answer()

# ---------- Проверка дневной и многодневной аренды ----------
async def check_daily_availability(chat_id: int, state: FSMContext, user_id: int):
    lang = await get_user_language(user_id)
    data = await state.get_data()
    workspace_id = data['selected_workspace']['id']
    selected_date = data['selected_date']
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        conflicting = await conn.fetchval("""
            SELECT 1 FROM bookings
            WHERE workspace_id = $1
              AND status IN ('pending', 'paid')
              AND DATE(start_time) = $2
            LIMIT 1
        """, workspace_id, selected_date)
    if conflicting:
        text = get_text('date_taken', lang).format(selected_date.strftime('%d.%m.%Y'))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text('back_to_date', lang), callback_data="back_to_date")],
            [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
        ])
        control_msg_id = data.get('dynamic_msg_id')
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=control_msg_id, reply_markup=kb)
    else:
        await confirm_booking(chat_id, state, user_id)

async def check_multiday_availability(chat_id: int, state: FSMContext, user_id: int):
    lang = await get_user_language(user_id)
    data = await state.get_data()
    # Проверяем наличие selected_workspace
    if 'selected_workspace' not in data:
        # Пытаемся восстановить из temp_booking
        temp = data.get('temp_booking')
        if temp and 'workspace_id' in temp:
            pool = dp['db_pool']
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM workspaces WHERE id = $1", temp['workspace_id'])
                if row:
                    ws = dict(row)
                    await state.update_data(selected_workspace=ws)
                else:
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
                    ])
                    await bot.send_message(chat_id, get_text('workspace_data_lost', lang), reply_markup=kb)
                    await state.clear()
                    return
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
            ])
            await bot.send_message(chat_id, get_text('workspace_data_lost', lang), reply_markup=kb)
            await state.clear()
            return
        # Обновляем данные
        data = await state.get_data()
    workspace_id = data['selected_workspace']['id']
    start_date = data['start_date']
    end_date = data['end_date']
    pool = dp['db_pool']
    current = start_date
    occupied_days = []
    async with pool.acquire() as conn:
        while current <= end_date:
            conflicting = await conn.fetchval("""
                SELECT 1 FROM bookings
                WHERE workspace_id = $1
                  AND status IN ('pending', 'paid')
                  AND DATE(start_time) = $2
                LIMIT 1
            """, workspace_id, current)
            if conflicting:
                occupied_days.append(current.strftime('%d.%m.%Y'))
            current += timedelta(days=1)
    if occupied_days:
        text = get_text('days_taken', lang).format(', '.join(occupied_days))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text('back_to_start_date', lang), callback_data="back_to_start_date")],
            [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
        ])
        control_msg_id = data.get('dynamic_msg_id')
        if control_msg_id:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=control_msg_id, reply_markup=kb)
        else:
            await bot.send_message(chat_id, text, reply_markup=kb)
    else:
        await confirm_booking(chat_id, state, user_id)

async def confirm_booking(chat_id: int, state: FSMContext, user_id: int):
    lang = await get_user_language(user_id)
    data = await state.get_data()
    ws = data['selected_workspace']
    rent_type = data['rent_type']
    total_price = 0
    description = ""
    if rent_type == "hourly":
        type_name = get_text('hourly', lang)
        start_time = data['start_time']
        end_time = data['end_time']
        hours = (end_time - start_time).seconds // 3600
        total_price = ws['price_per_hour'] * hours
        description = f"{start_time.strftime('%d.%m.%Y %H:%M')} – {end_time.strftime('%H:%M')}"
    elif rent_type == "daily":
        type_name = get_text('daily', lang)
        selected_date = data['selected_date']
        start_time = datetime.combine(selected_date, time(WORK_START_HOUR, 0))
        end_time = datetime.combine(selected_date, time(WORK_END_HOUR, 0))
        total_price = ws['price_per_day']
        description = get_text('daily_description', lang).format(date=selected_date.strftime('%d.%m.%Y'))
    else:
        type_name = get_text('multiday', lang)
        start_date = data['start_date']
        end_date = data['end_date']
        days = (end_date - start_date).days + 1
        start_time = datetime.combine(start_date, time(WORK_START_HOUR, 0))
        end_time = datetime.combine(end_date, time(WORK_END_HOUR, 0))
        total_price = ws['price_per_multi_day'] * days
        description = get_text('multiday_description', lang).format(start=start_date.strftime('%d.%m.%Y'), end=end_date.strftime('%d.%m.%Y'))

    await state.update_data(
        temp_booking={
            "workspace_id": ws['id'],
            "start_time": start_time,
            "end_time": end_time,
            "total_price": total_price,
            "description": description,
            "type_name": type_name,
            "workspace_name": ws['name']
        }
    )

    text = get_text('booking_summary', lang).format(
        workspace=ws['name'],
        type=type_name,
        description=description,
        total=total_price
    )

    # Проверка конфликта перед показом окна оплаты
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        conflicting = await conn.fetchval("""
            SELECT 1 FROM bookings
            WHERE workspace_id = $1
              AND status IN ('pending', 'paid')
              AND tstzrange(start_time, end_time) && tstzrange($2, $3)
            LIMIT 1
        """, ws['id'], start_time, end_time)
        if conflicting:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text('back_to_rent_type', lang), callback_data="back_to_rent_type")],
                [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
            ])
            control_msg_id = data.get('dynamic_msg_id')
            await bot.edit_message_text(
                text=get_text('booking_conflict', lang),
                chat_id=chat_id,
                message_id=control_msg_id,
                reply_markup=kb
            )
            await state.clear()
            return

    # Если конфликта нет, показываем окно выбора оплаты
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('pay_stars', lang), callback_data="pay_stars")],
        [InlineKeyboardButton(text=get_text('pay_tbank', lang), callback_data="pay_tbank_dummy")],
        [InlineKeyboardButton(text=get_text('back_to_rent_type', lang), callback_data="back_to_rent_type")],
        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="back_to_main_from_booking")]
    ])
    control_msg_id = data.get('dynamic_msg_id')
    await bot.edit_message_text(
        text=text,
        chat_id=chat_id,
        message_id=control_msg_id,
        reply_markup=kb
    )
    await state.set_state(BookingStates.waiting_for_payment)

# ---------- Оплата Telegram Stars ----------
@dp.callback_query(BookingStates.waiting_for_payment, lambda c: c.data == "pay_stars")
async def process_pay_stars(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    temp = data.get('temp_booking')
    if not temp:
        lang = await get_user_language(callback.from_user.id)
        await callback.answer(get_text('booking_data_not_found', lang), show_alert=True)
        await state.clear()
        return

    pool = dp['db_pool']
    async with pool.acquire() as conn:
        master = await conn.fetchrow("SELECT id FROM masters WHERE telegram_id = $1", callback.from_user.id)
        if not master:
            master = await conn.fetchrow(
                "INSERT INTO masters (telegram_id, full_name) VALUES ($1, $2) RETURNING id",
                callback.from_user.id, callback.from_user.full_name
            )
        master_id = master['id']
        conflicting = await conn.fetchval("""
            SELECT 1 FROM bookings
            WHERE workspace_id = $1
              AND status IN ('pending', 'paid')
              AND tstzrange(start_time, end_time) && tstzrange($2, $3)
            LIMIT 1
        """, temp['workspace_id'], temp['start_time'], temp['end_time'])
        if conflicting:
            await callback.message.edit_text("❌ К сожалению, это время уже занято. Попробуйте ещё раз.")
            await state.clear()
            await callback.answer()
            return
        booking = await conn.fetchrow("""
            INSERT INTO bookings (master_id, workspace_id, start_time, end_time, status, payment_method, payment_status, created_at, total_price)
            VALUES ($1, $2, $3, $4, 'pending', 'stars', 'pending', now(), $5)
            RETURNING id
        """, master_id, temp['workspace_id'], temp['start_time'], temp['end_time'], temp['total_price'])
        booking_id = booking['id']
        await state.update_data(booking_id=booking_id)

    stars_amount = 1   # тестовая цена
    payload = f"booking_{uuid.uuid4().hex}"
    await state.update_data(payment_payload=payload, user_id=callback.from_user.id)

    await callback.message.answer_invoice(
        title="Бронирование места",
        description=temp['description'],
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Аренда места", amount=stars_amount)],
        need_name=False,
        need_phone_number=False,
        need_email=False
    )
    await callback.answer()

# Обработка предварительного запроса
@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery, state: FSMContext):
    user_id = pre_checkout_query.from_user.id
    data = await state.get_data()
    booking_id = data.get('booking_id')
    if not booking_id:
        lang = await get_user_language(user_id)
        await pre_checkout_query.answer(ok=False, error_message=get_text('pre_checkout_no_booking', lang))
        return
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM bookings WHERE id = $1", booking_id)
        if status != 'pending':
            lang = await get_user_language(user_id)
            error_text = get_text('payment_timeout', lang)
            await pre_checkout_query.answer(ok=False, error_message=error_text)
            return
    await pre_checkout_query.answer(ok=True)

# Успешная оплата
@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    data = await state.get_data()
    booking_id = data.get('booking_id')
    if not booking_id:
        lang = await get_user_language(message.from_user.id)
        await message.answer(get_text('booking_id_not_found', lang))
        await state.clear()
        return

    pool = dp['db_pool']
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT b.status, b.start_time, b.end_time, w.name as workspace_name
            FROM bookings b
            JOIN workspaces w ON b.workspace_id = w.id
            WHERE b.id = $1
        """, booking_id)
        if not row:
            await message.answer(get_text('booking_expired', lang))
            await state.clear()
            return
        if row['status'] != 'pending':
            await message.answer(get_text('booking_already_processed', lang))
            await state.clear()
            return
        await conn.execute("UPDATE bookings SET status='paid', payment_status='paid' WHERE id=$1", booking_id)
        start_time = row['start_time']
        end_time = row['end_time']
        workspace_name = row['workspace_name']
        localized_workspace_name = get_workspace_name(workspace_name, lang)
        await state.update_data(
            booking_start=start_time,
            booking_end=end_time,
            workspace_name=localized_workspace_name,
            booking_id=booking_id
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('reminder_telegram_btn', lang), callback_data="reminder_telegram")],
        [InlineKeyboardButton(text=get_text('reminder_calendar_btn', lang), callback_data="reminder_calendar")],
        [InlineKeyboardButton(text=get_text('reminder_none_btn', lang), callback_data="reminder_none")]
    ])
    await message.answer(get_text('reminder_question', lang), reply_markup=kb)
    await state.set_state(BookingStates.choosing_reminder_type)

# ---------- Обработка выбора типа напоминания ----------
@dp.callback_query(BookingStates.choosing_reminder_type, lambda c: c.data == "reminder_none")
async def reminder_none(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    text = get_text('reminder_no_response', lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="to_main_menu_after_reminder")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await state.clear()
    await callback.answer()

@dp.callback_query(BookingStates.choosing_reminder_type, lambda c: c.data.startswith("reminder_"))
async def reminder_type_chosen(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    choice = callback.data.split("_")[1]  # 'telegram', 'calendar' или 'none'
    data = await state.get_data()
    start_time = data['booking_start']
    end_time = data.get('booking_end')   # должно быть сохранено в successful_payment_handler
    now = datetime.now()

    if choice == "calendar":
        # Генерация .ics файла
        filename = f"booking_{data['booking_id']}.ics"
        filepath = os.path.join("static", filename)
        create_ics_file(filepath, data['workspace_name'], start_time, end_time)
        with open(filepath, 'rb') as f:
            ics_content = f.read()
        await callback.message.answer_document(
            document=types.BufferedInputFile(ics_content, filename=filename),
            caption=get_text('reminder_calendar_file_caption', lang)
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="to_main_menu_after_reminder")]
        ])
        await callback.message.edit_text(get_text('reminder_calendar_sent', lang), reply_markup=kb)
        await state.clear()
        await callback.answer()
        return

    elif choice == "telegram":
        time_until_start = start_time - now
        options = []
        if time_until_start > timedelta(hours=1):
            options.append((get_text('reminder_1h', lang), 1))
        if time_until_start > timedelta(hours=3):
            options.append((get_text('reminder_3h', lang), 3))
        if time_until_start > timedelta(days=1):
            options.append((get_text('reminder_1d', lang), 24))

        if not options:
            await callback.message.answer(get_text('reminder_too_late', lang))
            await state.clear()
            await callback.answer()
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=f"remind_time_{hours}")]
            for text, hours in options
        ] + [
            [InlineKeyboardButton(text=get_text('back_to_reminder_type', lang), callback_data="back_to_reminder_type")],
            [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="to_main_menu_after_reminder")]
        ])
        await callback.message.edit_text(get_text('reminder_choose_time', lang), reply_markup=kb)
        await state.set_state(BookingStates.choosing_reminder_time)
        await callback.answer()
        return

    elif choice == "none":
        # Обработчик для "Никак"
        text = get_text('reminder_no_response', lang)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="to_main_menu_after_reminder")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
        await state.clear()
        await callback.answer()
        return

@dp.callback_query(BookingStates.choosing_reminder_time, lambda c: c.data == "back_to_reminder_type")
async def back_to_reminder_type(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('reminder_telegram_btn', lang), callback_data="reminder_telegram")],
        [InlineKeyboardButton(text=get_text('reminder_calendar_btn', lang), callback_data="reminder_calendar")],
        [InlineKeyboardButton(text=get_text('reminder_none_btn', lang), callback_data="reminder_none")]
    ])
    await callback.message.edit_text(get_text('reminder_question', lang), reply_markup=kb)
    await state.set_state(BookingStates.choosing_reminder_type)
    await callback.answer()

@dp.callback_query(BookingStates.choosing_reminder_time, lambda c: c.data.startswith("remind_time_"))
async def reminder_time_chosen(callback: CallbackQuery, state: FSMContext):
    hours_before = int(callback.data.split("_")[2])
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    start_time = data['booking_start']
    remind_at = start_time - timedelta(hours=hours_before)
    chat_id = callback.message.chat.id
    workspace_name = data['workspace_name']
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO reminders (chat_id, remind_at, booking_start, workspace_name, message_sent)
            VALUES ($1, $2, $3, $4, false)
        """, chat_id, remind_at, start_time, workspace_name)
    await schedule_reminder(chat_id, remind_at, workspace_name, start_time)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="to_main_menu_after_reminder")]
    ])
    await callback.message.edit_text(get_text('reminder_scheduled', lang).format(hours=hours_before), reply_markup=kb)
    await state.clear()
    await callback.answer()

def create_ics_file(filepath: str, workspace_name: str, start_time: datetime, end_time: datetime):
    cal = Calendar()
    cal.add('prodid', '-//Beauty Coworking//Booking//RU')
    cal.add('version', '2.0')
    event = Event()
    event.add('summary', f"Бронь в коворкинге «Девичьи дела»: {workspace_name}")
    event.add('dtstart', start_time)
    event.add('dtend', end_time)
    event.add('location', "ул. Республики, 26")
    event.add('description', f"Бронирование с {start_time.strftime('%d.%m.%Y %H:%M')} по {end_time.strftime('%d.%m.%Y %H:%M')}")
    # Напоминание за 2 часа
    alarm = Alarm()
    alarm.add('trigger', timedelta(hours=-2))
    alarm.add('action', 'DISPLAY')
    alarm.add('description', f"Напоминание: через 2 часа бронь {workspace_name}")
    event.add_component(alarm)
    cal.add_component(event)
    with open(filepath, 'wb') as f:
        f.write(cal.to_ical())

# Планировщик напоминаний
reminder_tasks = {}
async def schedule_reminder(chat_id: int, remind_at: datetime, workspace_name: str, start_time: datetime):
    now = datetime.now()
    delay = (remind_at - now).total_seconds()
    if delay <= 0:
        return
    task = asyncio.create_task(send_reminder_after_delay(chat_id, delay, workspace_name, start_time, remind_at))
    reminder_tasks[(chat_id, remind_at)] = task

async def send_reminder_after_delay(chat_id: int, delay: float, workspace_name: str, start_time: datetime, remind_at: datetime):
    await asyncio.sleep(delay)
    pool = dp['db_pool']
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT message_sent FROM reminders WHERE chat_id = $1 AND remind_at = $2", chat_id, remind_at)
        if not row or row['message_sent']:
            return
        await conn.execute("UPDATE reminders SET message_sent = true WHERE chat_id = $1 AND remind_at = $2", chat_id, remind_at)
    minutes_left = int((start_time - datetime.now()).total_seconds() // 60)
    # Язык берем из таблицы мастеров по chat_id (не реализовано, но можно оставить русским)
    await bot.send_message(chat_id, f"⏰ Напоминание: через {minutes_left} минут у вас бронь места «{workspace_name}».")

# ---------- Обработчик истечения времени ----------
async def expire_booking_task(booking_id: int, chat_id: int, payment_msg_id: int, user_id: int):
    await asyncio.sleep(120)
    pool = dp['db_pool']
    if not pool:
        return
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM bookings WHERE id = $1", booking_id)
        if status == 'pending':
            await conn.execute("DELETE FROM bookings WHERE id = $1", booking_id)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=payment_msg_id)
            except:
                pass
            lang = await get_user_language(user_id)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text('main_menu_btn', lang), callback_data="to_main_menu_from_expire")]
            ])
            await bot.send_message(chat_id, get_text('booking_pending_timeout', lang), reply_markup=kb)

@dp.callback_query(lambda c: c.data == "to_main_menu_from_expire")
async def to_main_menu_from_expire(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.clear()
    await callback.message.answer_photo(
        photo=DEFAULT_IMAGE,
        caption=get_text('main_menu_caption', lang),
        reply_markup=main_menu_keyboard(lang)
    )
    await callback.answer()

# ---------- Кнопка "Главное меню" после напоминания ----------
@dp.callback_query(lambda c: c.data == "to_main_menu_after_reminder")
async def to_main_menu_after_reminder(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.clear()
    await callback.message.answer_photo(
        photo=DEFAULT_IMAGE,
        caption=get_text('main_menu_caption', lang),
        reply_markup=main_menu_keyboard(lang)
    )
    await callback.answer()

# ---------- Возврат в главное меню из бронирования (удаление) ----------
@dp.callback_query(lambda c: c.data == "back_to_main_from_booking")
async def back_to_main_from_booking(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    for key in ['album_msg_ids', 'detail_album_msg_ids']:
        for msg_id in data.get(key, []):
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
            except:
                pass
    for key in ['control_msg_id', 'detail_control_msg_id']:
        msg_id = data.get(key)
        if msg_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=msg_id)
            except:
                pass
    try:
        await callback.message.delete()
    except:
        pass
    await state.clear()
    await callback.message.answer_photo(
        photo=DEFAULT_IMAGE,
        caption=get_text('main_menu_caption', lang),
        reply_markup=main_menu_keyboard(lang)
    )
    await callback.answer()

# ---------- Универсальный back_to_date ----------
@dp.callback_query(lambda c: c.data == "back_to_date")
async def back_to_date_universal(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    rent_type = data.get('rent_type')
    user_id = callback.from_user.id
    if rent_type == 'multiday':
        await ask_date(user_id, callback.message.chat.id, state, for_start=True)
        await state.set_state(BookingStates.choosing_start_date)
    else:
        await ask_date(user_id, callback.message.chat.id, state, for_start=False)
        await state.set_state(BookingStates.choosing_date)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_start_date")
async def back_to_start_date(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    rent_type = data.get('rent_type')
    if rent_type == 'multiday':
        await ask_date(callback.from_user.id, callback.message.chat.id, state, for_start=True)
        await state.set_state(BookingStates.choosing_start_date)
    else:
        # fallback
        await ask_date(callback.from_user.id, callback.message.chat.id, state, for_start=False)
        await state.set_state(BookingStates.choosing_date)
    await callback.answer()

# ---------- Заглушка для Т-Кассы ----------
@dp.callback_query(BookingStates.waiting_for_payment, lambda c: c.data == "pay_tbank_dummy")
async def pay_tbank_dummy(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await callback.answer(get_text('tbank_dummy_message', lang), show_alert=True)

# ---------- Отладчик необработанных колбэков ----------
@dp.callback_query()
async def debug_unhandled(callback: CallbackQuery):
    logging.warning(f"‼️ Необработанный callback: {callback.data}")
    lang = await get_user_language(callback.from_user.id)
    try:
        await callback.answer(get_text('unhandled_error', lang), show_alert=True)
    except:
        pass

# ---------- Запуск ----------
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())