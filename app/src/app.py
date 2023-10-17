import logging
import re

from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher.middlewares import BaseMiddleware
from pymongo import MongoClient

from config import CONNSTRING, DBNAME

def loadSettings():
    global TOKEN, ADMINCHATID, REGEX_LIST

    db = MongoClient(CONNSTRING).get_database(DBNAME)
    settings = db.settings.find_one({'_id': 'settings'})

    TOKEN = settings['TOKEN']
    ADMINCHATID = settings['ADMINCHATID']
    REGEX_LIST = settings['REGEX_LIST']


class LoggingMiddleware(BaseMiddleware):
    def __init__(self):
        super(LoggingMiddleware, self).__init__()

    async def on_post_process_message(self, message: types.Message, results, data: dict):
        text = message.text if message.text else message.caption
        if not text: return
        title = '[' + message.chat.title + '] ' if message.chat.title else ''
        logging.info(title + message.from_user.full_name + ': ' + text)

# Configure logging
logging.basicConfig(level=logging.INFO)

# settings
loadSettings()

# users cache
usersCache = {}

# Initialize bot and dispatcher
bot = Bot(token=TOKEN, parse_mode='HTML')
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())


def isSpam(text):
    if not text: return False
    for regex in REGEX_LIST:
        if re.search(regex, text, re.IGNORECASE + re.UNICODE):
            return True

    return False


def isUserLegal(message):
    key = str(message.chat.id) + '_' + str(message.from_user.id)
    if key in usersCache:
        return usersCache[key]

    db = MongoClient(CONNSTRING).get_database(DBNAME)
    doc = db.users.find_one({'_id': key})
    if not doc:
        doc = {
                '_id': key,
                'first_name': message.from_user.first_name,
                'last_name': message.from_user.last_name,
                'username': message.from_user.username,
                'chat_title': message.chat.title,
                'islegal': True
            }
        db.users.insert_one(doc)

    usersCache[key] = doc['islegal']
    return usersCache[key]


@dp.message_handler(content_types='new_chat_members')
async def processJoin(message: types.Message):
    await message.delete()

    db = MongoClient(CONNSTRING).get_database(DBNAME)
    for user in message.new_chat_members:
        await bot.send_message(ADMINCHATID, '👤 ' + user.full_name + ' joined ' + message.chat.title)
        docid = str(message.chat.id) + '_' + str(user.id)
        doc = db.users.find_one({'_id': docid})
        if not doc:
            data = {
                '_id': docid,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'username': user.username,
                'chat_title': message.chat.title,
                'islegal': False
            }
            db.users.insert_one(data)
            usersCache[docid] = False


@dp.message_handler(regexp=r'^unban$', chat_id=ADMINCHATID)
async def processCmdUnban(message: types.Message):
    if not (message.reply_to_message and message.reply_to_message.text):
        await message.answer('⚠ You must reply to message to use this command')
        return
    rg = re.search(r'\n(-?\d+_\d+)$', message.reply_to_message.text)
    if not rg:
        await message.answer('⚠ IDs not found in message')
        return
    (chat_id, user_id) = rg.group(1).split('_')
    result = await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
    if not result:
        await message.answer('⚠ User unban error')
        return
    await message.answer('✅ User unbanned successfully')


@dp.message_handler(commands='reload', chat_id=ADMINCHATID)
async def processCmdReload(message: types.Message):
    loadSettings()
    await message.answer('Settings sucessfully reloaded')


@dp.message_handler(content_types=types.ContentTypes.ANY)
async def processMsg(message: types.Message):
    if message.from_user.id == ADMINCHATID: return
    if message.sender_chat:
        await message.delete()
        return

    text = message.text if message.text else message.caption
    if not (text or message.reply_markup):
        return

    if isUserLegal(message):
        return

    db = MongoClient(CONNSTRING).get_database(DBNAME)
    key = str(message.chat.id) + '_' + str(message.from_user.id)

    if isSpam(text) or message.reply_markup:
        await bot.ban_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
        await message.forward(ADMINCHATID)
        await message.delete()
        await bot.send_message(ADMINCHATID, '💩 Spam from user: ' + message.from_user.full_name + '\n' + key)
        db.users.delete_one({'_id': key})
        usersCache.pop(key)
    else:
        db.users.update_one({'_id' : key}, {'$set': {'islegal': True}})
        usersCache[key] = True



if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)