import logging
import asyncio
import os
import traceback

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.utils.text_decorations import html_decoration as hd
from aiogram.utils.keyboard import KBuilder
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
import random
from pymongo import MongoClient

import config

connstring = config.CONNSTRING or os.getenv('connstring')
dbname = config.DBNAME or os.getenv('dbname')
db = MongoClient(connstring).get_database(dbname)

class Group:
    def __init__(self, chat_id=None, chat=None):
        if chat_id:
            data = GROUPS[int(chat_id)]
        elif chat:
            data = GROUPS[chat.id]
        else:
            raise('Error object initialization')

        self.emoji_list = list(data.get('emoji_list', EMOJI_LIST))
        self.emoji_rowsize = data.get('emoji_rowsize', EMOJI_ROWSIZE)
        self.welcome_text = data.get('welcome_text', WELCOME_TEXT)
        self.success_text = data.get('success_text', SUCCESS_TEXT)
        self.fail_text = data.get('fail_text', FAIL_TEXT)
        self.error_text = data.get('error_text', ERROR_TEXT)
        self.timeout_text = data.get('timeout_text', TIMEOUT_TEXT)
        self.captcha_timeout = data.get('captcha_timeout', CAPTCHA_TIMEOUT)
        self.logchatid = data.get('logchatid', LOGCHATID)
        self.delete_joins = data.get('delete_joins', DELETE_JOINS)
        self.delete_anonymous = data.get('delete_anonymous', DELETE_ANONYMOUS)

        if chat:
            self.welcome_text = self.welcome_text.replace('%CHAT_TITLE%', chat.title)

    def is_right_answer(self, answer):
        return answer == self.emoji_list[0]

    def buttons(self):
        kb = KBuilder()
        for emoji in random.sample(self.emoji_list, len(self.emoji_list)):
            kb.button(text=emoji, callback_data=f"{emoji}#{self.chat.id}#{self.chat.username or ''}")
        kb.adjust(self.emoji_rowsize)
        return kb.as_markup()

    def chat_link_button(self, chat_username):
        if not chat_username:
            return None
        return KBuilder().button(text='Перейти', url='https://t.me/' + chat_username).as_markup()


def loadSettings():
    global TOKEN, ADMINCHATID, LOGCHATID, ALLOWED_CHATS, GROUPS, EMOJI_LIST
    global WELCOME_TEXT, SUCCESS_TEXT, FAIL_TEXT, ERROR_TEXT, TIMEOUT_TEXT, CAPTCHA_TIMEOUT
    global EMOJI_ROWSIZE, HASHTAG, FORCE_SPAMCHECK, DELETE_JOINS, DELETE_ANONYMOUS

    try:
        settings = db.settings.find_one({'_id': 'settings'})

        TOKEN = settings['TOKEN']
        ADMINCHATID = settings['ADMINCHATID']
        LOGCHATID = settings.get('LOGCHATID', ADMINCHATID)
        ALLOWED_CHATS = [g['id'] for g in settings['GROUPS']] + \
            [g['logchatid'] for g in settings['GROUPS'] if 'logchatid' in g] + \
            [LOGCHATID]
        HASHTAG = settings['HASHTAG']
        GROUPS = {g['id']: g for g in settings['GROUPS']}
        EMOJI_LIST = settings['EMOJI_LIST']
        EMOJI_ROWSIZE = settings['EMOJI_ROWSIZE']
        WELCOME_TEXT = settings['WELCOME_TEXT']
        SUCCESS_TEXT = settings['SUCCESS_TEXT']
        FAIL_TEXT = settings['FAIL_TEXT']
        ERROR_TEXT = settings['ERROR_TEXT']
        TIMEOUT_TEXT = settings['TIMEOUT_TEXT']
        CAPTCHA_TIMEOUT = settings['CAPTCHA_TIMEOUT']
        DELETE_JOINS = settings['DELETE_JOINS']
        DELETE_ANONYMOUS = settings['DELETE_ANONYMOUS']
    except Exception:
        traceback.print_exc()
        return False

    return True


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# settings
if not loadSettings():
    exit()

# Initialize bot and dispatcher
bot = Bot(token=TOKEN, parse_mode='HTML')
dp = Dispatcher()
router = Router()


def isUserLegal(user: types.User, chat: types.Chat):
    doc = db.users.find_one({'_id': f'{chat.id}_{user.id}'})
    if doc:
        return doc['islegal']
    return False


async def isChatAllowed(chat: types.Chat):
    if chat.id in ALLOWED_CHATS:
        return True
    if chat.type == 'private':
        return True

    logging.warning(f'chat id {chat.id} ({chat.title}) is not allowed! Leaving chat')
    try:
        await chat.leave()
    except Exception:
        pass
    return False


@dp.update.outer_middleware()
async def outer_middleware(handler, event, data):
    chat = getattr(event.event, "chat", None)
    if chat and not await isChatAllowed(chat):
        return
    return await handler(event, data)


@router.message(F.new_chat_members)
async def deleteJoinMessage(message: types.Message):
    if message.chat.id not in GROUPS:
        return
    group = Group(chat=message.chat)
    if not group.delete_joins:
        return

    try:
        await message.delete()
    except Exception:
        logging.warning(f'Cannot delete join message in "{message.chat.title}" (no admin rights?)')


@router.message((F.text == '/reload') & (F.chat.id == ADMINCHATID))
async def processCmdReload(message: types.Message):
    if not loadSettings():
        await message.answer('Error!')
        return
    await message.answer('Settings sucessfully reloaded')


@router.chat_join_request()
async def processJoinRequest(update: types.ChatJoinRequest):
    chat = update.chat
    user = update.from_user
    if isUserLegal(user, chat):
        await bot.approve_chat_join_request(chat.id, user.id)
        return
    group = Group(chat=chat)
    logname = hd.quote(f'{user.full_name} @{user.username}' if user.username else user.full_name)
    message = await bot.send_message(user.id, group.welcome_text, reply_markup=group.buttons())
    await bot.send_message(group.logchatid, f'{HASHTAG}\n{logname} wants to join {chat.title}')
    await asyncio.sleep(group.captcha_timeout)
    try:
        await bot.decline_chat_join_request(chat.id, user.id)
    except Exception:
        return
    await message.edit_text(group.timeout_text)


@router.callback_query()
async def callbackHandler(query: types.CallbackQuery):
    user = query.from_user
    msg_id = query.message.message_id
    logname = hd.quote(f'{user.full_name} @{user.username}' if user.username else user.full_name)
    (answer, chat_id, chat_username) = query.data.split('#')
    group = Group(chat_id=chat_id)
    if group.is_right_answer(answer):
        try:
            await bot.approve_chat_join_request(chat_id, user.id)
        except Exception:
            await bot.edit_message_text(group.error_text, user.id, msg_id)
            return

        chat_link = None
        if chat_username:
            chat_link = KBuilder().button(text='Перейти', url='https://t.me/' + chat_username).as_markup()
        await bot.edit_message_text(group.success_text, user.id, msg_id, reply_markup=chat_link)
        await bot.send_message(group.logchatid, f'{HASHTAG}\n{logname} succeeded')
        docid = f'{chat_id}_{user.id}'
        doc = {
                '_id': docid,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'username': user.username,
                'chat_title': chat_username,
                'islegal': True
            }
        db.users.update_one({'_id': docid}, {'$set': doc}, upsert=True)
    else:
        await bot.edit_message_text(group.fail_text, user.id, msg_id)
        try:
            await bot.decline_chat_join_request(chat_id, user.id)
        except Exception:
            return
        await bot.send_message(group.logchatid, f'{HASHTAG}\n{logname} failed')


@router.message(F.chat.type != 'private')
async def processMsg(message: types.Message):
    if message.chat.id not in GROUPS:
        return
    group = Group(chat=message.chat)
    if message.sender_chat and group.delete_anonymous:
        await message.delete()


async def main():
    dp.include_router(router)
    dp.callback_query.middleware(CallbackAnswerMiddleware())
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())