import psycopg2
from psycopg2.extras import DictCursor
from config import load_config
import telebot
from telebot import types
import math
import os
from dotenv import load_dotenv


load_dotenv()
bot = telebot.TeleBot(os.getenv('TOKEN'))

# для ввода
user_states = {}


@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup()
    enter_btn = types.InlineKeyboardButton('Войти', callback_data='enter')
    markup.add(enter_btn)

    bot.send_message(message.chat.id,
                     f"Привет, {message.from_user.first_name}, это бот для помощи в управлении складом. "
                     "В нем можно добавлять товары в базу, получать информацию о поставщиках, товарах "
                     "и многое другое. Чтобы войти в систему склада нажмите кнопку \"Войти\".",
                     reply_markup=markup)


@bot.callback_query_handler(lambda call: call.data == 'main_menu')
def main_menu(call_or_message):
    markup = types.InlineKeyboardMarkup()
    manage_btn = types.InlineKeyboardButton("Управление", callback_data='manage')
    read_btn = types.InlineKeyboardButton("Просмотр", callback_data='read')
    info_btn = types.InlineKeyboardButton("Информация", callback_data='info')
    users_btn = types.InlineKeyboardButton("Пользователи", callback_data='users')
    markup.row(manage_btn, read_btn)
    markup.row(users_btn, info_btn)

    if isinstance(call_or_message, types.CallbackQuery):
        bot.send_message(call_or_message.message.chat.id, "Это главное меню склада. Выберите желаемое действие.",
                         reply_markup=markup)
    else:
        bot.send_message(call_or_message.chat.id, "Это главное меню склада. Выберите желаемое действие.",
                         reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == 'enter')
def enter_system(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    config = load_config()
    connection = psycopg2.connect(**config)
    cursor = connection.cursor()

    cursor.execute("INSERT INTO tg_users (username, first_name) "
                   "VALUES (%s, %s) "
                   "ON CONFLICT (username) "
                   "DO UPDATE SET date_joined = timezone('Europe/Moscow', CURRENT_TIMESTAMP)",
                   (call.from_user.username, call.from_user.first_name))

    connection.commit()
    cursor.close()
    connection.close()

    main_menu(call)


@bot.callback_query_handler(lambda call: call.data == 'manage')
def manage(call):
    markup = types.InlineKeyboardMarkup()
    write_import_btn = types.InlineKeyboardButton("Поставки", callback_data='write_import')
    write_export_btn = types.InlineKeyboardButton("Отгрузки", callback_data='write_export')
    main_menu_btn = types.InlineKeyboardButton("В меню", callback_data='main_menu')
    markup.row(write_import_btn, write_export_btn)
    markup.row(main_menu_btn)

    bot.edit_message_text("Управление баз склада.\nПОСЛЕ НАЧАЛА ВВОДА ОТМЕНИТЬ ЕГО УЖЕ БУДЕТ НЕЛЬЗЯ."
                          "\nВыберите действие.",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=markup)

# ---------------------------------------
# ----Код для ввода данных в таблицы-----
# ---------------------------------------


@bot.callback_query_handler(func=lambda call: call.data in ['write_import', 'write_export'])
def handle_write_action(call):
    action = call.data
    user_states[call.from_user.id] = {'action': action, 'step': 1, 'data': {}, 'message_id': call.message.message_id}

    bot.edit_message_text("ПОСЛЕ НАЧАЛА ВВОДА ОТМЕНИТЬ ЕГО УЖЕ БУДЕТ НЕЛЬЗЯ.",
                          call.message.chat.id, call.message.message_id)

    config = load_config()
    connection = psycopg2.connect(**config)
    cursor = connection.cursor()

    cursor.execute("SELECT MAX(product_id) FROM products")
    product_range = cursor.fetchone()[0] or 0

    connection.commit()
    cursor.close()
    connection.close()

    bot.send_message(call.message.chat.id,
                     f"Введите ID товара (от 1 до {product_range}):")

    bot.register_next_step_handler(call.message, handle_input)


def handle_input(message):
    user_id = message.from_user.id
    state = user_states.get(user_id, None)

    if state is None:
        bot.send_message(message.chat.id, "Что-то пошло не так. Попробуйте снова.")
        main_menu(message)
        return

    step = state['step']
    action = state['action']

    if step == 1:
        if not message.text.isdigit():
            bot.send_message(message.chat.id, "Неверный ввод! Пожалуйста, введите числовое значение для ID товара.")
            main_menu(message)
            return

        state['data']['product_id'] = message.text
        state['step'] = 2

        if action == 'write_import':
            config = load_config()
            connection = psycopg2.connect(**config)
            cursor = connection.cursor()

            cursor.execute("SELECT MAX(supplier_id) FROM suppliers")
            supplier_range = cursor.fetchone()[0] or 0

            connection.commit()
            cursor.close()
            connection.close()

            bot.send_message(message.chat.id,
                             f"Введите ID поставщика (от 1 до {supplier_range}):")
        elif action == 'write_export':
            bot.send_message(message.chat.id, "Введите количество (до 999):")
        bot.register_next_step_handler(message, handle_input)

    elif step == 2:
        if action == 'write_import':
            if not message.text.isdigit():
                bot.send_message(message.chat.id, "Неверный ввод! Пожалуйста, введите числовое значение "
                                                  "для ID поставщика.")
                main_menu(message)
                return

            state['data']['supplier_id'] = message.text
            state['step'] = 3

            bot.send_message(message.chat.id, "Введите количество (до 999):")
            bot.register_next_step_handler(message, handle_input)
        elif action == 'write_export':
            if not message.text.isdigit() or int(message.text) > 999:
                bot.send_message(message.chat.id, "Неверный ввод! Пожалуйста, введите числовое значение для "
                                                  "количества (до 999).")
                main_menu(message)
                return

            state['data']['quantity'] = message.text
            state['step'] = 3
            complete_export(message, state)

    elif step == 3:
        if not message.text.isdigit() or int(message.text) > 999:
            bot.send_message(message.chat.id, "Неверный ввод! Пожалуйста, введите числовое значение для "
                                              "количества (до 999).")
            main_menu(message)
            return

        state['data']['quantity'] = message.text
        complete_import(message, state)


def complete_import(message, state):
    user_id = message.from_user.id
    data = state['data']

    config = load_config()
    connection = psycopg2.connect(**config)
    cursor = connection.cursor()

    cursor.execute("SELECT user_id FROM tg_users WHERE username = %s", (message.from_user.username,))
    user_id_db = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM products WHERE product_id = %s", (data['product_id'],))
    if cursor.fetchone()[0] == 0:
        bot.send_message(message.chat.id, "Ошибка: Указанный ID товара не существует. Попробуйте снова.")
        del user_states[user_id]
        main_menu(message)
        return

    cursor.execute("SELECT COUNT(*) FROM suppliers WHERE supplier_id = %s", (data['supplier_id'],))
    if cursor.fetchone()[0] == 0:
        bot.send_message(message.chat.id, "Ошибка: Указанный ID поставщика не существует. Попробуйте снова.")
        del user_states[user_id]
        main_menu(message)
        return

    cursor.execute("INSERT INTO import_skld (product_id, supplier_id, quantity, user_id) VALUES (%s, %s, %s, %s)",
                   (data['product_id'], data['supplier_id'], data['quantity'], user_id_db))

    connection.commit()
    cursor.close()
    connection.close()

    del user_states[user_id]

    bot.send_message(message.chat.id, "Данные успешно внесены!")
    main_menu(message)


def complete_export(message, state):
    user_id = message.from_user.id
    data = state['data']

    config = load_config()
    connection = psycopg2.connect(**config)
    cursor = connection.cursor()

    cursor.execute("SELECT user_id FROM tg_users WHERE username = %s", (message.from_user.username,))
    user_id_db = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM products WHERE product_id = %s", (data['product_id'],))
    if cursor.fetchone()[0] == 0:
        bot.send_message(message.chat.id, "Ошибка: Указанный ID товара не существует. Попробуйте снова.")
        del user_states[user_id]
        main_menu(message)
        return

    cursor.execute("INSERT INTO export_skld (product_id, quantity, user_id) VALUES (%s, %s, %s)",
                   (data['product_id'], data['quantity'], user_id_db))

    connection.commit()
    cursor.close()
    connection.close()

    del user_states[user_id]

    bot.send_message(message.chat.id, "Данные успешно внесены!")
    main_menu(message)


# ----------------------------------------------
# -------КОД ДЛЯ КНОПКИ ПРОСМОТРА ТАБЛИЦ--------
# ----------------------------------------------

@bot.callback_query_handler(lambda call: call.data == 'read')
def read(call):
    markup = types.InlineKeyboardMarkup()
    read_import_btn = types.InlineKeyboardButton("Поставки", callback_data='read_import:1')
    read_export_btn = types.InlineKeyboardButton("Отгрузки", callback_data='read_export:1')
    read_suppliers_btn = types.InlineKeyboardButton("Поставщики", callback_data='read_suppliers:1')
    read_products_btn = types.InlineKeyboardButton("Товары", callback_data='read_products:1')
    main_menu_btn = types.InlineKeyboardButton("В меню", callback_data='main_menu')
    markup.row(read_import_btn, read_export_btn)
    markup.row(read_suppliers_btn, read_products_btn)
    markup.row(main_menu_btn)

    bot.edit_message_text("Просмотр баз склада. Выберите действие",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=markup)


# кнопка поставки
@bot.callback_query_handler(lambda call: call.data.startswith('read_import'))
def read_import(call):
    query = ("SELECT import_id, product_name, supplier_id, quantity FROM import_skld "
             "JOIN products ON import_skld.product_id = products.product_id")
    paginate_data(call, query, 'import')


# кнопка отгрузки
@bot.callback_query_handler(lambda call: call.data.startswith('read_export'))
def read_export(call):
    query = ("SELECT export_id, product_name, quantity FROM export_skld "
             "JOIN products ON export_skld.product_id = products.product_id")
    paginate_data(call, query, 'export')


# кнопка поставщики
@bot.callback_query_handler(lambda call: call.data.startswith('read_suppliers'))
def suppliers(call):
    query = "SELECT supplier_id, company_name, phone_number FROM suppliers"
    paginate_data(call, query, 'suppliers')


# кнопка товары
@bot.callback_query_handler(lambda call: call.data.startswith('read_products'))
def products(call):
    query = "SELECT product_id, product_name, stock_quantity FROM products"
    paginate_data(call, query, 'products')


# функция для отображения данных и кнопок страниц
def paginate_data(call, query, table_type):
    items_per_page = 10
    data_parts = call.data.split(':')
    current_page = int(data_parts[1]) if len(data_parts) > 1 else 1

    config = load_config()
    connection = psycopg2.connect(**config)
    cursor = connection.cursor()

    cursor.execute(query)
    data = cursor.fetchall()

    connection.commit()
    cursor.close()
    connection.close()

    if data:
        total_pages = math.ceil(len(data) / items_per_page)
        start_index = (current_page - 1) * items_per_page
        end_index = min(start_index + items_per_page, len(data))

        message_text = ""

        if table_type == 'import':
            message_text = "Данные о поставках:\n\n"
            for row in data[start_index:end_index]:
                import_id, product_name, supplier_id, quantity = row
                message_text += (f"ID поставки: {import_id}, Название товара: {product_name}, "
                                 f"ID поставщика: {supplier_id}, Количество: {quantity}\n\n")
        elif table_type == 'export':
            message_text = "Данные об отгрузках:\n\n"
            for row in data[start_index:end_index]:
                export_id, product_name, quantity = row
                message_text += (f"ID отгрузки: {export_id}, Название товара: {product_name}, "
                                 f"Количество: {quantity}\n\n")
        elif table_type == 'suppliers':
            message_text = "Данные о поставщиках:\n\n"
            for row in data[start_index:end_index]:
                supplier_id, company_name, phone_number = row
                message_text += (f"ID поставщика: {supplier_id}, Название: {company_name}, "
                                 f"Телефон: {phone_number}\n\n")
        elif table_type == 'products':
            message_text = "Данные о товарах:\n\n"
            for row in data[start_index:end_index]:
                product_id, product_name, stock_quantity = row
                message_text += (f"ID товара: {product_id}, Название: {product_name}, "
                                 f"Количество на складе: {stock_quantity}\n\n")

        markup = types.InlineKeyboardMarkup()
        row_buttons = []
        if current_page > 1:
            prev_button = types.InlineKeyboardButton("<<<", callback_data=f'read_{table_type}:{current_page - 1}')
            row_buttons.append(prev_button)
        if current_page < total_pages:
            next_button = types.InlineKeyboardButton(">>>", callback_data=f'read_{table_type}:{current_page + 1}')
            row_buttons.append(next_button)
        markup.row(*row_buttons)

        main_menu_btn = types.InlineKeyboardButton("В меню", callback_data='main_menu')
        markup.row(main_menu_btn)

        bot.edit_message_text(chat_id=call.message.chat.id,
                              message_id=call.message.message_id,
                              text=message_text,
                              reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, f"В базе данных нет данных о {table_type}.")


@bot.callback_query_handler(lambda call: call.data == 'info')
def info(call):

    markup = types.InlineKeyboardMarkup()
    main_menu_btn = types.InlineKeyboardButton("В меню", callback_data='main_menu')
    markup.row(main_menu_btn)

    bot.edit_message_text("--------------Информация--------------\n"
                          "Это бот помощник для управления базами склада.\n\n"
                          "В \"просмотр\" вы можете просматривать существующие базы склада.\n\n"
                          "В \"управление\" вы можете вносить информацию в \"Поставки\" и \"Отгрузки\". "
                          "Затем эта информация появится в базе.",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=markup)


@bot.callback_query_handler(lambda call: call.data == 'users')
def users(call):
    query = "SELECT username, date_joined FROM tg_users"
    paginate_users(call, query)

def paginate_users(call, query):
    items_per_page = 10
    data_parts = call.data.split(':')
    current_page = int(data_parts[1]) if len(data_parts) > 1 else 1

    config = load_config()
    connection = psycopg2.connect(**config)
    cursor = connection.cursor()

    cursor.execute(query)
    data = cursor.fetchall()

    connection.commit()
    cursor.close()
    connection.close()

    if data:
        total_pages = math.ceil(len(data) / items_per_page)
        start_index = (current_page - 1) * items_per_page
        end_index = min(start_index + items_per_page, len(data))

        message_text = "Данные о пользователях:\n\n"
        for row in data[start_index:end_index]:
            username, date_joined = row
            message_text += f"Имя пользователя: {username}, Дата присоединения: {date_joined}\n\n"

        markup = types.InlineKeyboardMarkup()
        row_buttons = []
        if current_page > 1:
            prev_button = types.InlineKeyboardButton("<<<", callback_data=f'users:{current_page - 1}')
            row_buttons.append(prev_button)
        if current_page < total_pages:
            next_button = types.InlineKeyboardButton(">>>", callback_data=f'users:{current_page + 1}')
            row_buttons.append(next_button)
        markup.row(*row_buttons)

        main_menu_btn = types.InlineKeyboardButton("В меню", callback_data='main_menu')
        markup.row(main_menu_btn)

        bot.edit_message_text(chat_id=call.message.chat.id,
                              message_id=call.message.message_id,
                              text=message_text,
                              reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, "В базе данных нет пользователей.")






if __name__ == '__main__':
    bot.polling(none_stop=True, interval=0)
