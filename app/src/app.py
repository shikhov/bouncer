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
users = {}

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


def getUser(message):
    key = str(message.chat.id) + '_' + str(message.from_user.id)
    if key in users:
        logging.info(key + ': from cache')
        return users[key]

    db = MongoClient(CONNSTRING).get_database(DBNAME)
    doc = db.users.find_one({'_id': key})
    if doc:
        users[key] = doc
        logging.info(key + ': from DB')
    else:
        logging.info(key + ': not found in DB, insert new')
        doc = {
                '_id': key,
                'first_name': message.from_user.first_name,
                'last_name': message.from_user.last_name,
                'username': message.from_user.username,
                'chat_title': message.chat.title,
                'islegal': True
            }
        db.users.insert_one(doc)
        users[key] = doc

    return doc


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
            users[docid] = data


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

    doc = getUser(message)
    logging.info(doc)
    if doc['islegal']: return

    db = MongoClient(CONNSTRING).get_database(DBNAME)

    if isSpam(text) or message.reply_markup:
        await bot.ban_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
        await message.forward(ADMINCHATID)
        await message.delete()
        await bot.send_message(ADMINCHATID, "💩 Spam from user: " + message.from_user.full_name)
        db.users.delete_one({'_id': doc['_id']})
        users.pop(doc['_id'])
    else:
        db.users.update_one({'_id' : doc.get('_id') }, {'$set': {'islegal': True}})
        users[doc['_id']]['islegal'] = True



if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)