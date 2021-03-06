#!/usr/bin/env python

import os
from time import sleep
import argparse
import glob
from multiprocessing import Process

import requests

from medusa import (configger as config,
                    logger as log,
                    communicator,
                    vlc)

if config.platform == "linux2":
    from gtk import DrawingArea

if config.platform == "win32":
    from win32api import keybd_event
    from win32con import (VK_MENU,
                          VK_TAB,
                          KEYEVENTF_KEYUP)

    def _str_to_bytes(string):
        if isinstance(string, unicode):
            return string.encode("utf-8")

        else:
            return string

    vlc.str_to_bytes = _str_to_bytes

communicate = communicator.Communicate()

def main():
    control = Control()

    communicate.listen()

    while True:
        control.action, control.option = communicate.accept()

        log.write("Received action '%s' and option '%s'." % (control.action,
                                                             control.option))

        control.get_state()

        if control.state == "Ended":
            control.stop()

            api.action("stop")

        log.write("Performing action '%s'." % (control.action))

        if control.action == "restart":
            break

        try:
            action_result = getattr(control, control.action)()

            if action_result:
                communicate.reply(action_result)

        except Exception as error:
            log.error("Failed to perform action '%s': %s." % (control.action,
                                                              error))

            continue

def media_watcher():
    log.write("Watcher launched.")

    communicate.receiver_hostname = config.hostname

    while True:
        with communicate:
            communicate.send("get_status")

            state, time_elapsed, time_total = communicate.receive()

            time_remaining = int(time_total) - int(time_elapsed)

            time_sleep = time_remaining / 2

            if time_sleep < 3:
                time_sleep = 0.5

        if state in ["Ended", "opped"]:
            with communicate:
                communicate.send(("play", "next"))

            log.write("Watcher exited.")

            break

        sleep(time_sleep)

class Api(object):
    def __init__(self):
        self.base_url = "http://%s:7000/api/" % (options.webmote)

    def action(self, action, option = None):
        if action == "begin":
            option = "%s-%s" % (option[0], option[1])

        action_url = "%s/%s/%s" % (config.hostname,
                                   action,
                                   option)

        url = self.base_url + action_url

        requests.get(url)

class Media(object):
    def __init__(self, directory, media_info):
        self.directory = directory
        self.media_info = media_info
        self.media_file = ""
        self.parts = []

    def get_media_file(self, media_partial):
        if media_partial == "disc":
            self.media_file = self.find_disc_type()

            log.write(self.media_file)

            return

        media_mount = options.source_mount

        if "Downloads-" in media_partial:
            media_partial = media_partial.strip("Downloads-")

            media_mount = options.downloads_mount

        if "Temporary-" in media_partial:
            media_partial = media_partial.strip("Temporary-")

            media_mount = options.temporary_mount

        if config.platform == "win32":
            media_partial = media_partial.replace("/", "\\")

        self.media_file = media_mount + "/" + media_partial

        if not os.path.exists(self.media_file):
            self.find_media_files()

    def find_disc_type(self):
	check = glob.glob("/media/*/VIDEO_TS")

        if check:
            return "dvd:///dev/dvd"

        else:
            return "bluray:///dev/dvd"

    def find_media_files(self):
        media_directory = os.path.dirname(self.media_file)

        for fle in os.listdir(media_directory):
            extension = os.path.splitext(fle)[1]

            extension = extension.lstrip(".").lower()

            if extension in config.video_extensions:
                media_path = "%s/%s" % (media_directory, fle)

                if " - Part 1 - " in fle:
                    self.media_file = media_path

                elif " - Part " in fle:
                    self.parts.append((media_path,
                                       self.directory,
                                       self.media_info))

class Control(object):
    def __init__(self):
        self.action = ""
        self.option = ""
        self.state = ""
        self.queue = []

        self.instance = vlc.Instance("--no-xlib")

        self.media_player = self.instance.media_player_new()

        if config.platform == "linux2":
            window = DrawingArea()

            def embed(*args):
                self.media_player.set_xwindow(window.window.xid)

                return True

            window.connect("map", embed)

    def get_status(self):
        time_elapsed, time_total = self.get_time()

        return (self.state, time_elapsed, time_total)

    def play(self):
        self.stop()

        if self.option == "next":
            if self.queue:
                media_file, directory, media_info = self.queue.pop(0)

                time_viewed = 0

            else:
                log.write("Cannot play next media, queue is empty.")

                return

        else:
            media_partial, time_viewed, directory, media_info = self.option

            media = Media(directory, media_info)

            media.get_media_file(media_partial)

            self.queue.extend(media.parts)

            media_file = media.media_file

        media_ready = self.instance.media_new(media_file)

        self.media_player.set_media(media_ready)

        api.action("begin", (directory, media_info))

        if self.state not in ["Playing", "Paused"]:
            media_watch = Process(target = media_watcher)

            media_watch.start()

        self.media_player.play()

        if time_viewed:
            self.media_player.set_time(time_viewed * 1000)

        self.media_player.set_fullscreen(1)

	self.mute()

        if self.media_player.audio_get_mute():
            self.mute()

        self.media_player.audio_set_volume(40)

        self.focus()

    def pause(self):
        self.media_player.pause()

    def rewind(self):
        current_time = self.media_player.get_time()

        if current_time > 30000:
            target_time = current_time - 30000

        else:
            target_time = 0

        self.media_player.set_time(target_time)

    def reset(self):
        self.media_player.set_time(0)

    def stop(self):
        self.media_player.stop()

        self.queue = []

    def volume_up(self):
        current_volume = self.media_player.audio_get_volume()

        target_volume = current_volume + 15

        if target_volume > 200:
            target_volume = 200

	log.write("Setting volume to '%s'." % (target_volume))

        self.media_player.audio_set_volume(target_volume)

    def volume_down(self):
        current_volume = self.media_player.audio_get_volume()

        target_volume = current_volume - 15

        if current_volume < 30:
            target_volume = 10

	log.write("Setting volume to '%s'." % (target_volume))

        self.media_player.audio_set_volume(target_volume)

    def mute(self):
        self.media_player.audio_toggle_mute()

    def get_state(self):
        self.state = str(self.media_player.get_state()).strip("State.")

    def get_time(self):
        time_elapsed = str(int(self.media_player.get_time()) / 1000)

        time_total = str(int(self.media_player.get_length()) / 1000)

        return time_elapsed, time_total

    def get_subtitle_tracks(self):
        result = self.media_player.video_get_spu_description()

        return ["null"] + result

    def get_audio_tracks(self):
        result = self.media_player.audio_get_track_description()

        return ["null"] + result

    def set_subtitle_track(self):
        self.media_player.video_set_spu(int(self.option))

    def set_audio_track(self):
        self.media_player.audio_set_track(int(self.option))

    def focus(self):
        if config.platform == "win32":
            keybd_event(VK_MENU, 0xb8, 0, 0)
            keybd_event(VK_TAB, 0x8f, 0, 0)
            keybd_event(VK_TAB, 0x8f, KEYEVENTF_KEYUP, 0)
            keybd_event(VK_MENU, 0xb8, KEYEVENTF_KEYUP, 0)

if __name__ == "__main__":
    log.write("Receiver launched.")

    parser = argparse.ArgumentParser(description = """The Downloads and
                                     Temporary mounts are optional. They
                                     provide functionality for the 'Recent'
                                     page.""")

    parser.add_argument("-w", "--webmote",
                        action = "store",
                        required = True,
                        help = "The hostname of the Webmote server.")

    parser.add_argument("-n", "--name",
                        action = "store",
                        required = True,
                        help = "A descriptive name for this Receiver.")

    parser.add_argument("-s", "--source_mount",
                        action = "store",
                        type = unicode,
                        required = True,
                        help = "The location of all indexed media.")

    parser.add_argument("-d", "--downloads_mount",
                        action = "store",
                        type = unicode,
                        default = None)

    parser.add_argument("-t", "--temporary_mount",
                        action = "store",
                        type = unicode,
                        default = None)

    options = parser.parse_args()

    api = Api()

    try:
        api.action("insert", options.name)

        main()

    finally:
        api.action("delete")

        communicate.close_connection()

        log.write("Receiver exited.")
