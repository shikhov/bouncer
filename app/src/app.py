import logging
import re
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.utils.text_decorations import html_decoration as hd
from pymongo import MongoClient

from regex_checker import RegexChecker
from config import CONNSTRING, DBNAME
db = MongoClient(CONNSTRING).get_database(DBNAME)


def loadSettings():
    global TOKEN, ADMINCHATID, LOGCHATID, ALLOWED_CHATS

    settings = db.settings.find_one({'_id': 'settings'})

    TOKEN = settings['TOKEN']
    ADMINCHATID = settings['ADMINCHATID']
    LOGCHATID = settings.get('LOGCHATID', ADMINCHATID)
    ALLOWED_CHATS = set(settings.get('ALLOWED_CHATS', {}))
    if not ALLOWED_CHATS:
        logging.warning('ALLOWED_CHATS is empty! It is recommended to fill in this field')

    stat = db.settings.find_one({'_id': 'stat'})
    regexChecker.load_list(settings['REGEX_LIST'], stat)


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
loadSettings()

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
    if chat.id == LOGCHATID:
        return False
    if not ALLOWED_CHATS:
        return True
    if chat.id in ALLOWED_CHATS:
        return True
    if chat.type == 'private':
        return True

    logging.info(f'chat id {chat.id} is not allowed! Leaving chat')
    try:
        await bot.leave_chat(chat.id)
    except Exception:
        pass
    return False


@router.message(F.new_chat_members)
async def removeJoinMessage(message: types.Message):
    if not await isChatAllowed(message.chat):
        return
    await message.delete()


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def processJoin(event: types.ChatMemberUpdated):
    if not await isChatAllowed(event.chat):
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
    loadSettings()
    await message.answer('Settings sucessfully reloaded')


async def checkForSpam(message: types.Message):
    chat = message.chat
    user = message.from_user

    if user.id == ADMINCHATID:
        return False
    if user.id == bot.id:
        return False

    if message.sender_chat:
        await message.delete()
        return True

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
            await bot.send_message(LOGCHATID, f'💩 Spam from user: {hd.quote(user.full_name)}\n{key}')

        await message.delete()
        db.users.delete_one({'_id': key})
        usersCache.pop(key)
        return True

    db.users.update_one({'_id' : key}, {'$set': {'islegal': True}})
    usersCache[key] = True
    return False


def updateStat(chat_id):
    stat = db.settings.find_one({'_id': 'stat'})
    today = str(datetime.today().date())
    stat['daily'][chat_id] = stat['daily'].get(chat_id, {})
    stat['daily'][chat_id][today] = stat['daily'][chat_id].get(today, 0) + 1
    regexChecker.updateStat(stat)
    db.settings.update_one({'_id': 'stat'}, {'$set': stat})


@router.message(F.chat.type != 'private')
async def processMsg(message: types.Message):
    if not await isChatAllowed(message.chat):
        return

    if await checkForSpam(message):
        updateStat(str(message.chat.id))

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())