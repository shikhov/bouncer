import logging
import re
import asyncio

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from pymongo import MongoClient

from config import CONNSTRING, DBNAME
db = MongoClient(CONNSTRING).get_database(DBNAME)


class RegexChecker:
    def __init__(self) -> None:
        self.rlist = {}
        self.matched_regex = None

    def load_list(self, regex_list):
        SUBS = {
            'а': 'a',
            'к': 'k',
            'и': 'u',
            'р': 'p',
            'о': 'o0',
            'е': 'ёe',
            'т': 't',
            'с': 'c',
            'н': 'h',
            'в': 'b',
            'з': '3',
            'у': 'y',
            'х': 'x'
        }
        tmp = {}
        stat = db.settings.find_one({'_id': 'stat'})

        for regex in regex_list:
            out_regex = ''
            for char in regex:
                if char in SUBS:
                    out_regex += '[' + char + SUBS[char] + ']'
                else:
                    out_regex += char
            tmp[regex] = {
                'regex': out_regex,
                'count': stat['regex'].get(regex, 0)
            }
            if regex.startswith(r'[\u'):
                tmp[regex]['flags'] = re.IGNORECASE + re.ASCII

        self.rlist = dict(sorted(tmp.items(), key=lambda item: item[1]['count'], reverse=True))

    def check(self, text):
        if not text: return False
        for key, value in self.rlist.items():
            regex = value['regex']
            flags = value.get('flags', re.IGNORECASE + re.UNICODE)
            if re.search(regex, text, flags):
                self.matched_regex = key
                return True

        return False

    def updateStat(self):
        if not self.matched_regex: return
        self.rlist[self.matched_regex]['count'] += 1
        self.rlist = dict(sorted(self.rlist.items(), key=lambda item: item[1]['count'], reverse=True))
        stat = db.settings.find_one({'_id': 'stat'})
        stat['regex'][self.matched_regex] = stat['regex'].get(self.matched_regex, 0) + 1
        db.settings.update_one({'_id': 'stat'}, {'$set': stat})
        self.matched_regex = None


def loadSettings():
    global TOKEN, ADMINCHATID, ALLOWED_CHATS

    settings = db.settings.find_one({'_id': 'settings'})

    TOKEN = settings['TOKEN']
    ADMINCHATID = settings['ADMINCHATID']
    regexChecker.load_list(settings['REGEX_LIST'])
    ALLOWED_CHATS = set(settings.get('ALLOWED_CHATS', {}))


def initServiceData():
    stat = db.settings.find_one({'_id': 'stat'})
    if not stat:
        stat_data = {
            'regex': {}
        }
        db.settings.update_one({'_id': 'stat'}, {'$set': stat_data}, upsert=True)


FORBIDDEN_ENTITIES = {'text_link', 'url', 'mention', 'custom_emoji'}

# Configure logging
logging.basicConfig(level=logging.INFO)

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


def isUserLegal(message: types.Message):
    key = str(message.chat.id) + '_' + str(message.from_user.id)
    if key in usersCache:
        return usersCache[key]

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


async def isChatAllowed(chat: types.Chat):
    if not ALLOWED_CHATS: return True
    if chat.id in ALLOWED_CHATS: return True
    if chat.type == 'private': return True

    logging.info(f'chat id {chat.id} is not allowed! Leaving chat')
    try:
        await bot.leave_chat(chat.id)
    except Exception:
        pass
    return False


@router.message(F.new_chat_members)
async def removeJoinMessage(message: types.Message):
    if not await isChatAllowed(message.chat): return
    await message.delete()


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def processJoin(event: types.ChatMemberUpdated):
    if not await isChatAllowed(event.chat): return

    user = event.new_chat_member.user
    chat = event.chat
    docid = str(chat.id) + '_' + str(user.id)
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


@router.message((F.text.lower() == 'unban') & (F.chat.id == ADMINCHATID))
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


@router.message(F.chat.type != 'private')
async def processMsg(message: types.Message):
    if not await isChatAllowed(message.chat): return
    if message.from_user.id == ADMINCHATID: return
    if message.from_user.id == bot.id: return

    if message.sender_chat:
        await message.delete()
        return

    if isUserLegal(message):
        return

    text = message.text or message.caption
    if not (text or message.reply_markup):
        return

    key = str(message.chat.id) + '_' + str(message.from_user.id)

    if message.reply_markup or checkEntities(message) or regexChecker.check(text):
        await bot.ban_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
        if not message.reply_markup:
            await message.forward(ADMINCHATID)
            await bot.send_message(ADMINCHATID, '💩 Spam from user: ' + message.from_user.full_name + '\n' + key)

        await message.delete()
        db.users.delete_one({'_id': key})
        usersCache.pop(key)
        regexChecker.updateStat()
    else:
        db.users.update_one({'_id' : key}, {'$set': {'islegal': True}})
        usersCache[key] = True


async def main():
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())