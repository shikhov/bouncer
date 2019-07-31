# -*- coding: utf-8 -*-

import json
import logging
import re
from urllib import urlencode
from urllib2 import URLError, urlopen

import webapp2
from google.appengine.ext import ndb
from config import TGTOKEN, TGMYCHATID, forwards

TGAPIURL = 'https://api.telegram.org/bot' + TGTOKEN + '/'

class MsgStats(ndb.Model):
    username = ndb.StringProperty()
    first_name = ndb.StringProperty()
    last_name = ndb.StringProperty()
    msg_count = ndb.IntegerProperty(default=1)
    enter_message_id = ndb.IntegerProperty()

def sendMessage(msg, chatid):
    urlopen(TGAPIURL + 'sendMessage', urlencode({
        'chat_id': chatid,
        'text': msg.encode('utf-8'),
        'disable_web_page_preview': 'true',
        'parse_mode': 'HTML',
    }))

def kickChatMember(chat_id, user_id):
    urlopen(TGAPIURL + 'kickChatMember', urlencode({
        'chat_id': chat_id,
        'user_id': user_id,
    }))

def deleteMessage(chat_id, message_id):
    urlopen(TGAPIURL + 'deleteMessage', urlencode({
        'chat_id': chat_id,
        'message_id': message_id,
    }))

def isSpam(text):
    if re.search(r'@\w+', text):
        return True
    if re.search(r'(^|\s+)t\.me/\w+', text):
        return True
    if re.search(r'(^|\s+)https?://\w+', text):
        return True
    if re.search(ur'крипт', text, re.IGNORECASE + re.UNICODE):
        return True
    if re.search(ur'битко(и|й)н', text, re.IGNORECASE + re.UNICODE):
        return True
    if re.search(ur'эфириум', text, re.IGNORECASE + re.UNICODE):
        return True
    if re.search(ur'блокчейн', text, re.IGNORECASE + re.UNICODE):
        return True
    if re.search(ur'обнал', text, re.IGNORECASE + re.UNICODE):
        return True
    if re.search(ur'пишите в лич', text, re.IGNORECASE + re.UNICODE):
        return True
    return False


class tgHandler(webapp2.RequestHandler):
    def post(self):
        body = json.loads(self.request.body)
        logging.info(json.dumps(body, indent=4))

        if 'message' in body:
            message = body['message']
            fr = message.get('from')
            user_id = fr.get('id')
            chat = message['chat']
            chat_id = chat.get('id')
            text = message.get('text')
            if not text:
                text = message.get('caption')
            message_id = message.get('message_id')
            username = fr.get('username')
            first_name = fr.get('first_name')
            last_name = fr.get('last_name')
            if last_name is None:
                dispname = first_name
            else:
                dispname = first_name + " " + last_name

            ms = MsgStats.get_or_insert(str(chat_id) + ',' + str(user_id))

            if 'new_chat_participant' in message:
                deleteMessage(chat_id, message_id)
                if not ms.first_name:
                    ms.username = username
                    ms.first_name = first_name
                    ms.last_name = last_name
                    ms.msg_count = 0
                    ms.enter_message_id = message_id
                    ms.put()
                sendMessage(dispname + " joined " + chat.get('title'), TGMYCHATID)

            if text:
                if ms.msg_count == 0:
                    if isSpam(text):
                        try:
                            kickChatMember(chat_id, user_id)
                            deleteMessage(chat_id, message_id)
                            sendMessage("Spam from user: " + dispname, TGMYCHATID)
                        except URLError as e:
                            sendMessage("Ban error!" + dispname + ": " + e.reason, TGMYCHATID)
                    else:
                        ms.msg_count = 1
                        ms.put()

            if chat_id in forwards and ms.msg_count > 0:
                urlopen(forwards[chat_id], self.request.body)


app = webapp2.WSGIApplication([
    ('/', tgHandler)
])
