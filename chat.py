#!/usr/bin/env python
#
# Copyright 2009 Facebook
#	was chatdemo.py included with tornado but hacked by sean to support inputting your own username instead of their google auth
# 	note: the google auth remains here but is unused. in case we want to add it later!
#		1/30/12
#Hacked by Nick for Bonfire
import logging
import tornado.auth
import tornado.escape
import tornado.ioloop
import tornado.options
import tornado.web
import os.path
import os
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
       	self.render("index.html", rooms=MessageMixin.waiters_dic.keys(), dic=MessageMixin.users_dic, error=None)

class RoomHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, room):
        self.render("room.html", messages=MessageMixin.cache_dic.get(room, []),
                    room=room,
                    users=MessageMixin.users_dic.get(room,[]))
    def post(self):
        new_room = self.get_argument("new_room_name")
        if new_room:
            for c in new_room:
                if c not in string.letters + string.digits + "-_":
                    self.render("index.html",
                                rooms=MessageMixin.waiters_dic.keys(),
                                dic=MessageMixin.users_dic,
                                error = "Invalid character " + c + " in room name.")
                                
            self.redirect("/room/" + self.get_argument("new_room_name"))

"""
waiters_dic is a dictionary from strings (room names) to lists of
of callbacks (people to inform when a new message arrives)

users_dic is a list from strings (room names) to lists of strings
(names of people who are in the room)

cache_dic is a list from strings (room names) to lists of messages.
Messages are dictionaries which typically include a body and a user,
among other things. Messages are also used to update the user pane,
though, in which case there is no body.
"""
class MessageMixin(object):
    waiters_dic = {}
    users_dic = {}
    cache_dic = {}
    cache_size = 200
    
    def wait_for_messages(self, callback, cursor=None):
        room_name = self.get_argument("room")
        cls = MessageMixin
        if room_name not in cls.cache_dic: cls.cache_dic[room_name] = []
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
        self.write("You are now logged out.<br>")
	self.write('<a href="login">Log in</a>')

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

#This file takes a POST method with a body containing some file and saves to static/files if under 131kB
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
