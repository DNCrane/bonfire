#!/usr/bin/env python
#
# Copyright 2009 Facebook
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# Based on chatdemo.py included with tornado.
#

import logging
import tornado.auth
import tornado.escape
import tornado.ioloop
import tornado.options
import tornado.web
import os.path
import os
import xml.dom.minidom
import uuid
from tornado.options import define, options
from httpExists import *
import string

define("port", default=8888, help="run on the given port", type=int)

"""
This works by long polling: http://en.wikipedia.org/wiki/Long_polling#Long_polling

The clients (people waiting in chatrooms) send us requests to be informed when a new
message arrives. These requests are handled in the function wait_for_message in
the MessageMixin class. The dictionary waiters_dic maps room names to lists of listeners
(listeners=callbacks=waiters).

So we hang onto callbacks for all of the clients that requested to wait for messages, and
when a message finally arrives, we inform all of them using the callback. This is done in
new_messages in MessageMixin. Our list of listeners is then cleared, so people waiting
in the chatroom have to send another request in order to receive later messages. I'm not
really sure why it's done this way -- it seems like we should just be able to hold onto
the same callback until the listener disconnects (closing connections is described in the
next paragraph), but this is how the sample chat application did it. If I have time I'll
try it the way I just described and see if that works.

If a listener disconnects, cancel_wait is called, which removes the listener from the list of
listeners.
--Dave
"""
class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", MainHandler),
            (r"/room", RoomHandler),
            (r"/room/(?P<room>[a-zA-Z0-9\-\_]*)", RoomHandler),
            (r"/login", LoginHandler),
            (r"/logout", LogoutHandler),
            (r"/roomlogin", RoomLoginHandler),
            (r"/a/message/new", MessageNewHandler),
            (r"/a/message/updates", MessageUpdatesHandler),
            (r"/messages", MessageHandler),
	    (r"/upload/(?P<room>[a-zA-Z0-9\-\_]*)", UploadFileHandler),
	    (r"/files/(?P<filename>[a-zA-Z0-9\-\_\.]*)", FileDownloadHandler),
            #(r"/ban", BanHandler),
            ]

        settings = dict(
            cookie_secret="43oETzK99aqGaYdkL5gEmGeJJFuYh7EQnp2XdTP1o/Vo=",
            login_url="/login",
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            xsrf_cookies=True,
            autoescape="xhtml_escape",
            )
	#users = set()
	#banned_users = set()
        tornado.web.Application.__init__(self, handlers, **settings)


class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        user = self.get_secure_cookie("user")
        if not user: return None
        return user

class FileDownloadHandler(BaseHandler):
    def get(self,filename):
	path = os.path.join(os.getcwd(), 'static/files/' + filename)
	retFile = open(path,"r")
	self.set_header ('Content-Disposition', 'attachment; filename=' + filename) 
	self.write(retFile.read())

class MainHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
       	self.render("index.html", rooms=MessageMixin.waiters_dic.keys(), dic=MessageMixin.users_dic, 
                    has_pw=MessageMixin.has_pw_dic,error=None)

class RoomLoginHandler(BaseHandler):
    def post(self):
        room_name = self.get_argument("room_name")
        room_pass = self.get_argument("room_password")
        self.clear_cookie(room_name)
        self.set_secure_cookie(room_name,room_pass)
        self.redirect("/room/"+room_name)

class RoomHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, room):
        password = self.get_secure_cookie(room)
        pw_dic = MessageMixin.rooms_pw_dic

        if not pw_dic.has_key(room):
            self.render("room.html", messages = MessageMixin.cache_dic.get(room, []),
                    room = room,
                    users = MessageMixin.users_dic.get(room,[]))
        elif pw_dic[room] == password:
            self.render("room.html", messages = MessageMixin.cache_dic.get(room, []),
                    room = room,
                    users = MessageMixin.users_dic.get(room,[]))
        else:
            self.render("roomlogin.html", room = room)

    def post(self):
        new_room = self.get_argument("new_room_name")
        new_room_pass = self.get_argument("new_room_pass", None)
        pw_dic = MessageMixin.rooms_pw_dic
        has_pw_dic = MessageMixin.has_pw_dic

        if not pw_dic.has_key(new_room) and new_room_pass != None:
            pw_dic[new_room] = new_room_pass
            has_pw_dic[new_room] = True
            self.clear_cookie(new_room)
            self.set_secure_cookie(new_room, new_room_pass)

        if new_room:
            for c in new_room:
                if c not in string.letters + string.digits + "-_":
                    self.render("index.html",
                                rooms=MessageMixin.waiters_dic.keys(),
                                dic=MessageMixin.users_dic,
                                error = "Invalid character " + c + " in room name.")
        
	    #if log doesn't exist, create file                    
        if not os.path.exists(new_room + '.xml'):
            doc = xml.dom.minidom.Document()
            chat_log = doc.createElementNS("Bonfire", "log")
            doc.appendChild(chat_log)
            with open(new_room + '.xml', "w") as f:
                f.write(doc.toxml())
            self.redirect("/room/" + self.get_argument("new_room_name"))
	    #Parse and display log
	    doc = xml.dom.minidom.parse(new_room + '.xml')
	    MessageList = doc.getElementsByTagName('message')
	    i = 0
	    for node in MessageList:
		self.addMessage(node)

        self.redirect("/room/" + self.get_argument("new_room_name"))

    #Function to add messages from log to cache
    def addMessage(self, node):
	new_room = self.get_argument("new_room_name")
	cls = MessageMixin
	message = {
	    "id": str(uuid.uuid4()),
	    "from": node.childNodes[1].childNodes[0].nodeValue,
	    "user_type": "user",
	    "body": node.childNodes[0].childNodes[0].nodeValue,
	    "images": [],
    	    "user_list": [],
	    }
	message["html"] = self.render_string("message.html", message=message)
	if new_room not in cls.cache_dic: cls.cache_dic[new_room] = []
        cls.cache_dic[new_room].extend([message])

"""
waiters_dic is a dictionary from strings (room names) to lists of
of callbacks (people to inform when a new message arrives)

users_dic is a list from strings (room names) to lists of strings
(names of people who are in the room)

cache_dic is a list from strings (room names) to lists of messages.
Messages are dictionaries which typically include a body and a user,
among other things. Messages are also used to update the user pane,
though, in which case there is no body.

rooms_pw_dic holds room passwords here because couldn't get it to work elsewhere
"""
class MessageMixin(object):
    rooms_pw_dic = {}
    has_pw_dic = {}
    waiters_dic = {}
    users_dic = {}
    cache_dic = {}
    cache_size = 200
    
    def wait_for_messages(self, callback, cursor=None):
        room_name = self.get_argument("room")
        cls = MessageMixin
        if room_name not in cls.cache_dic: 
	    cls.cache_dic[room_name] = []
        if room_name not in cls.users_dic: cls.users_dic[room_name] = set()
        if cursor:
            cache = cls.cache_dic[room_name]
            index = 0
            for i in xrange(len(cache)):
                index = len(cache) - i - 1 
		if cache[index]["id"] == cursor: break
            recent = cache[index + 1:]
            if recent:
                callback(recent)
                return
        logging.info("Request to wait for room " + room_name)
        if room_name in cls.waiters_dic:
            cls.waiters_dic[room_name].add(callback)
        else:
            cls.waiters_dic[room_name] = set([callback])
        user = self.get_secure_cookie("user")
        if user not in cls.users_dic[room_name]:
            cls.users_dic[room_name].add(user)
            message = {
                "id": str(uuid.uuid4()),
                "from": self.current_user,
                "user_type": self.get_secure_cookie("user_type"),
                "user_list": str(list(cls.users_dic[room_name])),
                }
            self.new_messages([message])

    def cancel_wait(self, callback):
        cls = MessageMixin
        room_name = self.get_argument("room")
        cls.waiters_dic[room_name].remove(callback)
        cls.users_dic[room_name].remove(self.get_secure_cookie("user"))
        logging.info(str(self))
        #del cls.waiter_names[callback]
        #logging.info("canceling wait" + str(cls.waiter_names))
        logging.info("closing connection to " + room_name)
        message = {
            "id": str(uuid.uuid4()),
            "from": self.current_user,
            "user_type": self.get_secure_cookie("user_type"),
            "user_list": str(list(cls.users_dic[room_name])),
            }
        self.new_messages([message])

    def new_messages(self, messages, room=None):
        cls = MessageMixin
        room_name = self.get_argument("room")
        #logging.info("Sending new message to %r listeners", len(cls.waiters))
        #logging.info(str(cls.waiter_names))
        for callback in cls.waiters_dic[room_name]:
            try:
                callback(messages)
            except:
                logging.error("Error in waiter callback", exc_info=True)
        cls.waiters_dic[room_name] = set()
        if room_name not in cls.cache_dic: cls.cache_dic[room_name] = []
        cls.cache_dic[room_name].extend(messages)
        if len(cls.cache_dic[room_name]) > self.cache_size:
            cls.cache_dic[room_name] = cls.cache_dic[room_name][-self.cache_size:]


class MessageNewHandler(BaseHandler, MessageMixin):
    @tornado.web.authenticated
    def post(self):
#        if self.current_user in self.banned_users:
#              self.write("Sorry, banned.")
#	else:
        room_name = self.get_argument("room")
        logging.info("Receiving message from room " + room_name)
        body = self.get_argument("body")
        images = []
        img_extensions=[".png",".jpg",".gif","jpeg"]
        for word in body.split(" "):
            if len(word)>14 and word[-4:] in img_extensions and word[:7] in ["http://","https:/"]:
                images+=[word]
        message = {
            "id": str(uuid.uuid4()),
            "from": self.current_user,
            "user_type": self.get_secure_cookie("user_type"),
            "body": body,
            "images": images,
            "user_list": str(list(MessageMixin.users_dic[room_name])),
            }	        
        message["html"] = self.render_string("message.html", message=message)
        if self.get_argument("next", None):
            self.redirect(self.get_argument("next"))
        else:
            self.write(message)
            self.new_messages([message])

	# Add message to xml log
	doc = xml.dom.minidom.parse(room_name + '.xml')
	message_element = doc.createElementNS("Bonfire", "message")
	body_element = doc.createElementNS("Bonfire", "body")
	from_element = doc.createElementNS("Bonfire", "from")
	chat_log = doc.childNodes[0]
	messagebody = doc.createTextNode(message["body"])
	messagefrom = doc.createTextNode(message["from"])
	chat_log.appendChild(message_element)
	message_element.appendChild(body_element)
	body_element.appendChild(messagebody)
	message_element.appendChild(from_element)
	from_element.appendChild(messagefrom)
	with open(room_name + '.xml', "w") as f:
		f.write(doc.toxml())


class MessageUpdatesHandler(BaseHandler, MessageMixin):
    @tornado.web.authenticated
    @tornado.web.asynchronous
    def post(self):
        cursor = self.get_argument("cursor", None)
        self.wait_for_messages(self.on_new_messages,
                               cursor=cursor)
    def on_new_messages(self, messages):
        # Closed client connection
        if self.request.connection.stream.closed():
            return
        self.finish(dict(messages=messages))
    def on_connection_close(self):
        self.cancel_wait(self.on_new_messages)


class LoginHandler(BaseHandler):
    users = set()     

    def get(self):
        self.render("login.html", error="")

    def post(self):
	name = self.get_argument("name")
	if name in self.users:
            self.render("login.html" , error = "Name " + self.get_argument("name") + " taken. Try a different one please.")
        elif len(name)>30:
            self.render("login.html", error = "That's a pretty long name...you ought to pick something shorter.")
        else:
            self.users.add(name)
            self.set_secure_cookie("user", name)
            logging.info(name + " logged in")
            self.set_secure_cookie("user_type", "TestValue")	
	self.redirect("/")



class AuthLoginHandler(BaseHandler, tornado.auth.GoogleMixin):
    @tornado.web.asynchronous
    def get(self):
        if self.get_argument("openid.mode", None):
            self.get_authenticated_user(self.async_callback(self._on_auth))
            return
        self.authenticate_redirect(ax_attrs=["name"])
    def _on_auth(self, user):
        if not user:
            raise tornado.web.HTTPError(500, "Google auth failed")
        self.set_secure_cookie("user", tornado.escape.json_encode(user))
        self.redirect("/")


class LogoutHandler(BaseHandler):
    def get(self):
        name=self.get_secure_cookie("user")
        LoginHandler.users.discard(name)
        self.clear_cookie("user")
        self.render("logout.html")

class MessageHandler(BaseHandler): #I wrote this to see what's in the message cache. Pretty sure it's all the messages.
    def get(self):
	self.write("<html>")
        for message in MessageMixin.cache:
            self.write(message["body"] + "<br>")

class BanHandler(BaseHandler):
#TODO: make this work. at all.
#    banned_users = set()
    def post(self):
        name = self.get_argument("user_to_ban")
        if name not in self.banned_users:
                self.banned_users.add(name)

#This file takes a POST method with a body containing some file and saves to static/files if under 200kB
class UploadFileHandler(BaseHandler):
    def get(self, room):
	self.render("uploadfile.html", room=room, status="", submit=False)
    def post(self, room):
	upload = self.request.files['newfile'][0]
	destination = os.path.join(os.getcwd(), 'static/files/' + upload['filename'])
	f=open(destination, 'wb')
	if (len(upload['body']) < 200000):
        	f.write(upload['body'])
                self.render("uploadfile.html", room=room, status="File uploaded.", submit=False);
	else:
		os.remove(destination)
                self.render("uploadfile.html", room=room, status="Error: File too large.",submit=True);
        f.close()

def main():
    tornado.options.parse_command_line()
    app = Application()
    app.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()
if __name__ == "__main__":
    main()
