import logging
import re
import asyncio
import os
from datetime import datetime
import traceback

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.utils.text_decorations import html_decoration as hd
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
import random
from pymongo import MongoClient

from regex_checker import RegexChecker
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
        self.force_spamcheck = data.get('force_spamcheck', FORCE_SPAMCHECK)
        self.delete_joins = data.get('delete_joins', DELETE_JOINS)
        self.delete_anonymous = data.get('delete_anonymous', DELETE_ANONYMOUS)

        if chat:
            self.welcome_text = self.welcome_text.replace('%CHAT_TITLE%', chat.title)

    def random_emoji(self):
        return random.sample(self.emoji_list, len(self.emoji_list))

    def is_right_answer(self, answer):
        return answer == self.emoji_list[0]


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
        FORCE_SPAMCHECK = settings['FORCE_SPAMCHECK']
        DELETE_JOINS = settings['DELETE_JOINS']
        DELETE_ANONYMOUS = settings['DELETE_ANONYMOUS']

        stat = db.settings.find_one({'_id': 'stat'})
        regexChecker.load_list(settings['REGEX_LIST'], stat)
    except Exception:
        traceback.print_exc()
        return False

    return True


def initServiceData():
    stat_struct = {
        'regex': {},
        'daily': {}
    }
    stat = db.settings.find_one({'_id': 'stat'})
    if stat:
        for key, value in stat_struct.items():
            stat[key] = stat.get(key, value)
    else:
        stat = stat_struct
    db.settings.update_one({'_id': 'stat'}, {'$set': stat}, upsert=True)


FORBIDDEN_ENTITIES = {'text_link', 'url', 'mention', 'custom_emoji'}

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

regexChecker = RegexChecker()
usersCache = {}

# service data
initServiceData()

# settings
if not loadSettings():
    exit()

# Initialize bot and dispatcher
bot = Bot(token=TOKEN, parse_mode='HTML')
dp = Dispatcher()
router = Router()


def checkEntities(message: types.Message):
    entities = message.entities or message.caption_entities or []
    for entity in entities:
        if entity.type in FORBIDDEN_ENTITIES:
            return True
    return False


def isUserLegal(user: types.User, chat: types.Chat):
    key = f'{chat.id}_{user.id}'
    if key in usersCache:
        return usersCache[key]

    doc = db.users.find_one({'_id': key})
    if not doc:
        doc = {
                '_id': key,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'username': user.username,
                'chat_title': chat.title,
                'islegal': True
            }
        db.users.insert_one(doc)

    usersCache[key] = doc['islegal']
    return usersCache[key]


async def isChatAllowed(chat: types.Chat):
    if chat.id in ALLOWED_CHATS:
        return True
    if chat.type == 'private':
        return True

    logging.warning(f'chat id {chat.id} ({chat.title}) is not allowed! Leaving chat')
    try:
        await bot.leave_chat(chat.id)
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


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def processJoin(event: types.ChatMemberUpdated):
    if event.chat.id not in GROUPS:
        return
    group = Group(chat=event.chat)
    if not group.force_spamcheck:
        return

    user = event.new_chat_member.user
    chat = event.chat
    docid = f'{chat.id}_{user.id}'
    data = {
        '_id': docid,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'username': user.username,
        'chat_title': chat.title,
    }

    doc = db.users.find_one({'_id': docid})
    if doc:
        data['islegal'] = doc['islegal']
    else:
        data['islegal'] = False

    db.users.update_one({'_id': docid}, {'$set': data}, upsert=True)
    usersCache[docid] = data['islegal']


@router.message((F.text.lower() == 'unban') & (F.chat.id == LOGCHATID))
async def processCmdUnban(message: types.Message):
    if not (message.reply_to_message and message.reply_to_message.text):
        await message.answer('⚠ You must reply to message to use this command')
        return
    rg = re.search(r'\n(-?\d+_\d+)$', message.reply_to_message.text)
    if not rg:
        await message.answer('⚠ IDs not found in message')
        return
    key = rg.group(1)
    (chat_id, user_id) = key.split('_')
    try:
        result = await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
        if not result:
            await message.answer('⚠ User unban error')
            return
    except TelegramBadRequest as e:
        await message.answer('⚠ ' + e.message)
        return

    db.users.insert_one({'_id': key, 'islegal': True})
    usersCache[key] = True
    await message.answer('✅ User unbanned successfully')


@router.message((F.text == '/reload') & (F.chat.id == ADMINCHATID))
async def processCmdReload(message: types.Message):
    if not loadSettings():
        await message.answer('Error!')
        return

    await message.answer('Settings sucessfully reloaded')


async def checkForSpam(message: types.Message):
    chat = message.chat
    user = message.from_user

    if user.id == ADMINCHATID:
        return False
    if user.id == bot.id:
        return False

    if isUserLegal(user, chat):
        return False

    text = message.text or message.caption
    if not (text or message.reply_markup):
        return False

    key = f'{chat.id}_{user.id}'

    if message.reply_markup or checkEntities(message) or regexChecker.check(text):
        await bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
        if not message.reply_markup:
            await message.forward(LOGCHATID)
            await bot.send_message(LOGCHATID, f'{HASHTAG}\n💩 Spam from user: {hd.quote(user.full_name)}\n{key}')

        await message.delete()
        db.users.delete_one({'_id': key})
        usersCache.pop(key)
        return True

    db.users.update_one({'_id' : key}, {'$set': {'islegal': True}})
    usersCache[key] = True
    return False


def updateStat(message: types.Message):
    chat_id = str(message.chat.id)
    stat = db.settings.find_one({'_id': 'stat'})
    today = str(datetime.today().date())
    stat['daily'][chat_id] = stat['daily'].get(chat_id, {})
    stat['daily'][chat_id][today] = stat['daily'][chat_id].get(today, 0) + 1
    regexChecker.updateStat(stat)
    db.settings.update_one({'_id': 'stat'}, {'$set': stat})


@router.chat_join_request()
async def processJoinRequest(update: types.ChatJoinRequest):
    chat = update.chat
    user = update.from_user
    group = Group(chat=chat)
    logname = f'{hd.quote(user.full_name)} (@{user.username})' if user.username else hd.quote(user.full_name)
    builder = InlineKeyboardBuilder()
    for emoji in group.random_emoji():
        builder.button(text=emoji, callback_data=f'{emoji}#{chat.id}#{chat.username}')
    builder.adjust(group.emoji_rowsize)
    message = await bot.send_message(user.id, group.welcome_text, reply_markup=builder.as_markup())
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
    logname = f'{hd.quote(user.full_name)} (@{user.username})' if user.username else hd.quote(user.full_name)
    (answer, chat_id, chat_username) = query.data.split('#')
    group = Group(chat_id=chat_id)
    if group.is_right_answer(answer):
        try:
            await bot.approve_chat_join_request(chat_id, user.id)
        except Exception:
            await bot.edit_message_text(group.error_text, user.id, msg_id)
            return

        kb = InlineKeyboardBuilder().button(text='Перейти', url='https://t.me/' + chat_username)
        await bot.edit_message_text(group.success_text, user.id, msg_id, reply_markup=kb.as_markup())
        await bot.send_message(group.logchatid, f'{HASHTAG}\n{logname} succeeded')
        if not group.force_spamcheck:
            return

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
        usersCache[docid] = True
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

    if group.force_spamcheck:
        if await checkForSpam(message):
            updateStat(message)


async def main():
    dp.include_router(router)
    dp.callback_query.middleware(CallbackAnswerMiddleware())
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())