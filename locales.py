# locales.py

TEXTS = {
    'ru': {
        # Главное меню
        'welcome': "👋 Добро пожаловать в коворкинг «Девичьи дела»!\nЯ помогу забронировать место.",
        'main_menu_caption': "Выберите действие:",
        'book_btn': "📅 Забронировать",
        'about_btn': "💬 О коворкинге",
        'lang_btn': "🇷🇺/🇺🇸 Язык",
        'back_btn': "⬅️ Назад",
        'main_menu_btn': "🏠 Главное меню",

        # О коворкинге
        'about_text': "📍 <b>Коворкинг «Девичьи дела»</b>\nАдрес: г. Тюмень ул. Республики, 26\n🕒 Работаем ежедневно с 6:00 до 22:00\n📞 Контакт: @devichyi_dela",

        # Язык
        'choose_language': "Выберите язык:",
        'lang_changed': "Язык успешно изменён на русский.",
        'lang_ru': "🇷🇺 Русский",
        'lang_en': "🇺🇸 English",

        # Категории
        'choose_category': "Выберите категорию места:",
        'cat_couch': "🛏 Кушетки",
        'cat_hairdresser': "💇‍♀️ Парикмахерские места",
        'cat_dressing': "🎭 Гримерки",
        'no_workspaces': "В этой категории пока нет мест.",
        'workspace_not_found': "Место не найдено.",
        'cat_couch_202': '🛏 Кушетки 202',
        'cat_dressing_202': '🎭 Гримерки 202',
        'cat_dressing_201': '🎭 Гримерки 201',
        'cat_hairdresser_201': '💺 Кресла 201',

        # Выбор места
        'select_workspace': "Выберите место:",
        'prev_category': "⬅️ Предыдущая категория",
        'next_category': "Следующая категория ➡️",
        'back_to_categories': "⬅️ К категориям",

        # Типы аренды
        'choose_rental_type': "Выберите тип аренды:",
        'hourly': "⏱ Почасовая (1 час)",
        'daily': "☀️ На день (6:00-22:00)",
        'multiday': "📅 На несколько дней (фикс. ставка)",
        'back_to_workspace': "⬅️ Назад к месту",

        # Календарь
        'choose_date': "Выберите дату:",
        'choose_start_date': "Выберите дату начала:",
        'choose_month': "Выберите месяц:",
        'choose_year': "Выберите год:",
        'back_to_rent_type': "⬅️ Назад",
        'back_to_month_selection': "⬅️ Назад к выбору месяца",
        'months': ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"],
        'weekdays_short': ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
        'back_to_start_date': "⬅️ К выбору начала",
        'choose_concrete_date': "Выберите конкретное число", 

        # Выбор времени (почасовая)
        'choose_start_time': "Выберите время начала для {}:",
        'choose_duration': "Вы выбрали начало в {}. Укажите длительность:",
        'no_free_hours': "На этот день нет свободных часов. Попробуйте другую дату.",
        'back_to_date': "⬅️ К выбору даты",

        # Проверка доступности дневной/многодневной
        'date_taken': "К сожалению, {} уже занят. Выберите другую дату.",
        'days_taken': "Некоторые дни уже заняты: {}. Выберите другой диапазон.",

        # Подтверждение брони
        'booking_summary': (
        "✅ Подтверждение бронирования:\n"
        "Место: {workspace}\n"
        "Тип: {type}\n"
        "{description}\n"
        "Сумма: {total} руб{stars_line}\n\n"
        "Выберите способ оплаты:"),
        'booking_summary_stars': " (или {stars} звёзд, если выбран Telegram Stars)",
        'daily_description': "Весь день {date} (6:00-22:00)",
        'multiday_description': "с {start} по {end} (ежедневно 6:00-22:00)",
        'pay_stars': "⭐ Оплатить Stars",
        'pay_tbank': "💳 Т-Касса (заглушка)",
        'back_to_rent_type_from_pay': "⬅️ Назад к выбору типа",

        # Оплата и таймаут
        'booking_pending_timeout': "⏰ Время бронирования истекло. Пожалуйста, начните бронирование заново.",
        'payment_timeout': "Время бронирования истекло. Пожалуйста, начните заново.",
        'booking_expired': "Время бронирования истекло. Повторите попытку.",
        'booking_already_processed': "Бронь уже обработана.",

        # Напоминания
        'reminder_question': "✅ Бронь успешно оплачена!\nКак вы хотите получить напоминание о брони?",
        'reminder_telegram_btn': "📱 Напомнить в Telegram",
        'reminder_calendar_btn': "📅 Добавить в календарь",
        'reminder_none_btn': "❌ Никак",
        'reminder_choose_time': "Выберите, за сколько отправить напоминание:",
        'reminder_1h': "1 час",
        'reminder_3h': "3 часа",
        'reminder_1d': "1 день",
        'reminder_too_late': "До начала брони слишком мало времени, чтобы запланировать напоминание.",
        'reminder_scheduled': "✅ Напоминание запланировано за {hours} час(ов) до начала брони.",
        'reminder_calendar_added': "Нажмите на кнопку, чтобы добавить событие в календарь.\nЕсли кнопка не работает, файл также доступен по ссылке.",
        'reminder_no_response': "Хорошо, будем вас ждать в коворкинге «Девичьи дела»!\n📍 Адрес: ул. Республики, 26\n🕒 Работаем ежедневно с 6:00 до 22:00\n\nДо встречи!",
        'add_to_calendar_btn': "📅 Добавить в календарь",
        'back_to_reminder_type': "⬅️ Назад к выбору напоминания",

        # Блокировка
        'blocked_message': "🚫 Ваш аккаунт заблокирован администратором. По вопросам обратитесь в поддержку.",

        # Календарь
        'reminder_calendar_file_caption': "📅 Нажмите на файл, чтобы добавить событие в календарь.",
        'reminder_calendar_sent': "Файл календаря отправлен. Скачайте его и откройте – событие добавится в ваш календарь.",

        'workspaces': {
            'Кушетка 1 (у окна)': 'Кушетка 1 (у окна)',
            'Кушетка 2': 'Кушетка 2',
            'Парикмахерское кресло 1': 'Парикмахерское кресло 1',
            'Парикмахерское кресло 2': 'Парикмахерское кресло 2',
            'Гримерка 1': 'Гримерка 1',
            'Гримерка 2': 'Гримерка 2',
        },

        'price_per_hour': 'Почасово',
        'price_per_day': 'На день',
        'price_per_multi_day': 'Многодневная',
        'booking_expired': 'Бронь устарела или была удалена.',
        'booking_already_processed': 'Бронь уже обработана.',
        
        # Обработчики
        'choose_concrete_date': "Выберите конкретное число",
        'slot_already_taken': "К сожалению, этот час уже занят. Выберите другое время.",
        'booking_conflict': "❌ К сожалению, это время уже занято. Пожалуйста, выберите другое.",
        'booking_data_not_found': "Ошибка: данные брони не найдены.",
        'booking_id_not_found': "Ошибка: идентификатор брони не найден.",
        'pre_checkout_no_booking': "Бронь не найдена. Попробуйте снова.",
        'tbank_dummy_message': "Оплата через Т-Кассу находится в разработке. Пожалуйста, выберите другой способ оплаты.",
        'unhandled_error': "⚠️ Что-то пошло не так",
        'unknown_rental_type': "Неизвестный тип аренды",
        'end_date_before_start': "Дата окончания не может быть раньше даты начала. Попробуйте снова.",
        'edit_message_not_found': "Ошибка: не найдено сообщение для редактирования. Попробуйте начать бронирование заново.",
        'workspace_data_lost': "Данные о месте утеряны. Пожалуйста, начните бронирование заново.",
        # НЕ ПЕРЕВЕДЕНО
        'cancel_booking_btn': '❌ Отменить бронь',
        'cancel_booking_prompt': 'Если вы передумали, можете отменить бронь, пока она не оплачена.',
        'booking_cancelled': 'Бронь отменена.',
        'booking_already_paid': 'Бронь уже оплачена, отмена невозможна.',
        'day_already_started': 'Сегодняшний день уже начался, забронировать его нельзя. Выберите другой день.',
        

    },
    'en': {
        # Main menu
        'welcome': "👋 Welcome to 'Devichyi dela' coworking!\nI will help you book a place.",
        'main_menu_caption': "Choose an action:",
        'book_btn': "📅 Book",
        'about_btn': "💬 About coworking",
        'lang_btn': "🇷🇺/🇺🇸 Language",
        'back_btn': "⬅️ Back",
        'main_menu_btn': "🏠 Main menu",

        # About coworking
        'about_text': "📍 <b>'Devichyi dela' coworking</b>\nAddress: Tyumen, 26 Respubliki St.\n🕒 Open daily from 6:00 to 22:00\n📞 Contact: @devichyi_dela",

        # Language
        'choose_language': "Choose language:",
        'lang_changed': "Language successfully changed to English.",
        'lang_ru': "🇷🇺 Русский",
        'lang_en': "🇺🇸 English",

        # Categories
        'choose_category': "Choose a workspace category:",
        'cat_couch': "🛏 Couches",
        'cat_hairdresser': "💇‍♀️ Hairdressing places",
        'cat_dressing': "🎭 Makeup rooms",
        'no_workspaces': "No workspaces in this category yet.",
        'workspace_not_found': "Workspace not found.",
        'cat_couch_202': '🛏 Couch 202',
        'cat_dressing_202': '🎭 Makeup rooms 202',
        'cat_dressing_201': '🎭 Makeup rooms 201',
        'cat_hairdresser_201': '💺 Chairs 201',

        # Select workspace
        'select_workspace': "Select a workspace:",
        'prev_category': "⬅️ Previous category",
        'next_category': "Next category ➡️",
        'back_to_categories': "⬅️ Back to categories",

        # Rental types
        'choose_rental_type': "Choose rental type:",
        'hourly': "⏱ Hourly (1 hour)",
        'daily': "☀️ Full day (6:00-22:00)",
        'multiday': "📅 Several days (fixed rate)",
        'back_to_workspace': "⬅️ Back to workspace",

        # Calendar
        'choose_date': "Select a date:",
        'choose_start_date': "Select start date:",
        'choose_month': "Select month:",
        'choose_year': "Select year:",
        'back_to_rent_type': "⬅️ Back",
        'back_to_month_selection': "⬅️ Back to month selection",
        'months': ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        'weekdays_short': ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
        'back_to_start_date': "⬅️ Back to start date",
        'choose_concrete_date': "Select a specific date",  

        # Choose time (hourly)
        'choose_start_time': "Choose start time for {}:",
        'choose_duration': "You selected start at {}. Choose duration:",
        'no_free_hours': "No free hours on this day. Try another date.",
        'back_to_date': "⬅️ Back to date",

        # Availability checks
        'date_taken': "Unfortunately, {} is already taken. Choose another date.",
        'days_taken': "Some days are already taken: {}. Choose another range.",

        # Booking confirmation
        'booking_summary': (
        "✅ Booking confirmation:\n"
        "Workspace: {workspace}\n"
        "Type: {type}\n"
        "{description}\n"
        "Amount: {total} RUB{stars_line}\n\n"
        "Choose payment method:"
        ),
        'booking_summary_stars': " (or {stars} stars if Telegram Stars selected)",
        'daily_description': "Full day {date} (6:00-22:00)",
        'multiday_description': "from {start} to {end} (daily 6:00-22:00)",
        'pay_stars': "⭐ Pay with Stars",
        'pay_tbank': "💳 T‑Kassa (dummy)",
        'back_to_rent_type_from_pay': "⬅️ Back to rental type",

        # Payment and timeout
        'booking_pending_timeout': "⏰ Booking time has expired. Please start the booking again.",
        'payment_timeout': "Booking time has expired. Please start over.",
        'booking_expired': "Booking time has expired. Please try again.",
        'booking_already_processed': "Booking already processed.",

        # Reminders
        'reminder_question': "✅ Booking paid successfully!\nHow would you like to receive a reminder?",
        'reminder_telegram_btn': "📱 Telegram reminder",
        'reminder_calendar_btn': "📅 Add to calendar",
        'reminder_none_btn': "❌ No reminder",
        'reminder_choose_time': "Choose how long before to send reminder:",
        'reminder_1h': "1 hour",
        'reminder_3h': "3 hours",
        'reminder_1d': "1 day",
        'reminder_too_late': "There is too little time before the booking to schedule a reminder.",
        'reminder_scheduled': "✅ Reminder scheduled {hours} hour(s) before the booking.",
        'reminder_calendar_added': "Click the button below to add event to your calendar.\nIf the button doesn't work, the file is also available via the link.",
        'reminder_no_response': "Okay, we will be waiting for you at 'Devichyi dela' coworking!\n📍 Address: 26 Respubliki St.\n🕒 Open daily from 6:00 to 22:00\n\nSee you!",
        'add_to_calendar_btn': "📅 Add to calendar",
        'back_to_reminder_type': "⬅️ Back to reminder type",

        # Blocked
        'blocked_message': "🚫 Your account has been blocked by the administrator. Please contact support.",

        # Calendar
        'reminder_calendar_file_caption': "📅 Click on the file to add the event to your calendar.",
        'reminder_calendar_sent': "Calendar file sent. Download and open it – the event will be added to your calendar.",

        'workspaces': {
            'Кушетка 1 (у окна)': 'Couch 1 (by window)',
            'Кушетка 2': 'Couch 2',
            'Парикмахерское кресло 1': 'Hairdresser chair 1',
            'Парикмахерское кресло 2': 'Hairdresser chair 2',
            'Гримерка 1': 'Makeup room 1',
            'Гримерка 2': 'Makeup room 2',
        },
        'price_per_hour': 'Hourly rate',
        'price_per_day': 'Daily rate',
        'price_per_multi_day': 'Multi-day rate',
        'booking_expired': 'Booking expired or was deleted.',
        'booking_already_processed': 'Booking already processed.',

        # Handlers
        'choose_concrete_date': "Select a specific date",
        'slot_already_taken': "Sorry, this hour is already taken. Choose another time.",
        'booking_conflict': "❌ Unfortunately, this time slot is already taken. Please choose another.",
        'booking_data_not_found': "Error: booking data not found.",
        'booking_id_not_found': "Error: booking ID not found.",
        'pre_checkout_no_booking': "Booking not found. Please try again.",
        'tbank_dummy_message': "Payment via T‑Kassa is under development. Please choose another payment method.",
        'unhandled_error': "⚠️ Something went wrong",
        'unknown_rental_type': "Unknown rental type",
        'end_date_before_start': "End date cannot be earlier than start date. Please try again.",
        'edit_message_not_found': "Error: message to edit not found. Please start booking again.",
        'workspace_data_lost': "Workspace data lost. Please start booking again.",

    }
}