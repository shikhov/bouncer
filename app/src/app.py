import logging
import asyncio

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
import random

from pymongo import MongoClient

from config import CONNSTRING, DBNAME
db = MongoClient(CONNSTRING).get_database(DBNAME)


def loadSettings():
    global TOKEN, ADMINCHATID, LOGCHATID, ALLOWED_CHATS, EMOJI_LIST, RIGHT_ANSWER
    global SUCCESS_TEXT, FAIL_TEXT

    settings = db.settings.find_one({'_id': 'settings'})

    TOKEN = settings['TOKEN']
    ADMINCHATID = settings['ADMINCHATID']
    LOGCHATID = settings.get('LOGCHATID', ADMINCHATID)
    ALLOWED_CHATS = set(settings.get('ALLOWED_CHATS', {}))
    EMOJI_LIST = list(settings['EMOJI_LIST'])
    RIGHT_ANSWER = EMOJI_LIST[0]
    SUCCESS_TEXT = settings['SUCCESS_TEXT']
    FAIL_TEXT = settings['FAIL_TEXT']
    if not ALLOWED_CHATS:
        logging.warning('ALLOWED_CHATS is empty! It is recommended to fill in this field')


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# settings
loadSettings()

# Initialize bot and dispatcher
bot = Bot(token=TOKEN, parse_mode='HTML')
dp = Dispatcher()
router = Router()


@router.message((F.text == '/reload') & (F.chat.id == ADMINCHATID))
async def processCmdReload(message: types.Message):
    loadSettings()
    await message.answer('Settings sucessfully reloaded')


@router.chat_join_request()
async def processJoinRequest(update: types.ChatJoinRequest):
    chat = update.chat
    user = update.from_user
    builder = InlineKeyboardBuilder()
    for emoji in random.sample(EMOJI_LIST, len(EMOJI_LIST)):
        builder.button(text=emoji, callback_data=f'{emoji}#{chat.id}#{chat.username}')
    builder.adjust(4, 4)
    text = f'Для вступления в чат "{chat.title}" нажмите на значок, соответствующий тематике чата'
    await bot.send_message(chat_id=update.user_chat_id, text=text, reply_markup=builder.as_markup())
    await bot.send_message(LOGCHATID, f'{user.full_name} wants to join {chat.title}')



@router.callback_query()
async def callbackHandler(query: types.CallbackQuery):
    user = query.from_user
    msg_id = query.message.message_id
    logname = f'{user.full_name} (@{user.username})' if user.username else user.full_name
    (answer, chat_id, chat_username) = query.data.split('#')
    if answer == RIGHT_ANSWER:
        kb = InlineKeyboardBuilder().button(text='Перейти', url='https://t.me/' + chat_username)
        await bot.edit_message_text(SUCCESS_TEXT, chat_id=user.id, message_id=msg_id, reply_markup=kb.as_markup())
        await bot.approve_chat_join_request(chat_id=chat_id, user_id=user.id)
        await bot.send_message(LOGCHATID, f'{logname} succeeded')
    else:
        await bot.edit_message_text(FAIL_TEXT, chat_id=user.id, message_id=msg_id)
        await bot.decline_chat_join_request(chat_id=chat_id, user_id=query.from_user.id)
        await bot.send_message(LOGCHATID, f'{logname} failed')



async def main():
    dp.include_router(router)
    dp.callback_query.middleware(CallbackAnswerMiddleware())
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())