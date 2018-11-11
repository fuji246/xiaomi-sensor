#!/usr/bin/env python

from sensor import *
import settings
import requests
import datetime
import os
import time

def IsBetweenTime(start_time, end_time):
    toMinutes = lambda h, m: 60 * int(h) + int(m)
    now = datetime.datetime.now()
    current = toMinutes(now.hour, now.minute)
    start_minute = toMinutes(*(start_time.split(':')))
    end_minute = toMinutes(*(end_time.split(':')))
    if end_minute < start_minute:
        end_minute += toMinutes(24, 0)
    if current < start_minute:
        current += toMinutes(24, 0)
    return current <= end_minute

def validBetweenTime(start_time, end_time):
    def decoratorFunction(func):
        def wrapper(*args, **kwargs):
            if IsBetweenTime(start_time, end_time):
                func(*args, **kwargs)
            else:
                logger.warn('not validBetweenTime, %s - %s, %s' % \
                    (start_time, end_time, datetime.datetime.now()))
        return wrapper
    return decoratorFunction

class IftttMixin(object):
    def _trigger(self, url):
        try:
            r = requests.post(url)
            r.raise_for_status()
            logger.info('%s [%s]' % (url, r))
            return True
        except requests.exceptions.RequestException as e:
            logger.error('trigger %s error: %s' % (url, e))
            return False


class OnOffControl(IftttMixin):

    def __init__(self, on_url, off_url):
        self.on = False
        self.on_url = on_url
        self.off_url = off_url

    def turnOn(self):
        if not self.on:
            self._trigger(self.on_url)
            self.on = not self.on

    def turnOff(self):
        if self.on:
            self._trigger(self.off_url)
            self.on = not self.on


class LightControl(OnOffControl):

    validTime = validBetweenTime(settings.LIVING_ROOM_LIGHT_START_TIME, settings.LIVING_ROOM_LIGHT_END_TIME)
    
    def __init__(self, toggle_url, on_url=None, off_url=None):
        super(LightControl, self).__init__(on_url, off_url)
        self.toggle_url = toggle_url

    def onTimer(self):
        if not IsBetweenTime(settings.LIVING_ROOM_LIGHT_START_TIME, settings.LIVING_ROOM_LIGHT_END_TIME):
            self.turnOff()

    def toggle(self):
        self._trigger(self.toggle_url)
        self.on = not self.on

    @validTime
    def turnOnInValidTime(self):
        self.turnOn()

    @validTime
    def turnOffInValidTime(self):
        self.turnOff()


class HumidifierControl(OnOffControl):
    pass


class FanControl(OnOffControl):
    pass


class PurifyControl(OnOffControl):
    pass


class HDMIControl():

    def __init__(self):
        self.on = True

    def toggle(self):
        if self.on:
            os.system('sudo tvservice -o')
            self.on = False
        else:
            os.system('sudo tvservice -p')
            os.system('sudo chvt 9')
            os.system('sudo chvt 7')
            self.on = True


class Automation(object):

    def __init__(self):
        self.light = LightControl(
            settings.TOOGLE_LIVING_ROOM_LIGHT_URL,
            settings.TURN_ON_LIVING_ROOM_LIGHT_URL,
            settings.TURN_OFF_LIVING_ROOM_LIGHT_URL,
        )
        self.light.turnOff()

        self.bedroom_light = LightControl(settings.TOOGLE_BED_ROOM_LIGHT_URL)
        self.bedroom_light.turnOff()

        self.humidifier = HumidifierControl(
            settings.TURN_ON_BEDROOM_HUMIDIFIER,
            settings.TURN_OFF_BEDROOM_HUMIDIFIER
        )

        self.fan = FanControl(
            settings.TURN_ON_BEDROOM_FAN,
            settings.TURN_OFF_BEDROOM_FAN
        )

        self.purify = PurifyControl(
            settings.TURN_ON_BEDROOM_PURIFY,
            settings.TURN_OFF_BEDROOM_PURIFY
        )

        self.hdmi = HDMIControl()
        self.gateway = None

    def onTimer(self):
        self.light.onTimer()

    def onGatewayEvent(self, device):
        logger.info('==> onGatewayEvent, %s' % device)
        self.gateway = device

    def onSensorHtEvent(self, device):
        logger.info('==> onSensorHtEvent, %s' % device)
        if device.humidity <= settings.HUMIDITY_LOWER_THRSHOLD:
            self.humidifier.turnOn()
        elif device.humidity >= settings.HUMIDITY_UPPER_THRSHOLD:
            self.humidifier.turnOff()

        if device.temperature >= settings.TEMPERATURE_UPPER_THRSHOLD:
            self.fan.turnOn()
        elif device.temperature <= settings.TEMPERATURE_LOWER_THRSHOLD:
            self.fan.turnOff()
    
    def onSwitchEvent(self, device):
        logger.info('==> onSwitchEvent, %s' % device)
        if device.status == 'click':
            self.bedroom_light.toggle()
        elif device.status == 'double_click':
            self.humidifier.turnOn()
        elif device.status == 'long_click_press':
            self.hdmi.toggle()
        elif device.status == 'long_click_release':
            pass

    def onMotionEvent(self, device):
        logger.info('==> onMotionEvent, %s' % device)
        if device.status == 'motion':
            self.light.turnOnInValidTime()
        elif device.status == 'no_motion' and device.no_motion_seconds >= settings.NO_MOTION_TIMEOUT:
            self.light.turnOffInValidTime()

    def onDoorEvent(self, device):
        logger.info('==> onDoorEvent, %s' % device)
        if IsBetweenTime(settings.ALARM_START_TIME, settings.ALARM_END_TIME):
            if device.status == 'open':
                self.gateway.playRingTone(XMGateway.ringstone_siren)


if __name__ == '__main__':
    automation = Automation() 
    rules = {
        'f0b429b442b1': automation.onGatewayEvent,
        '158d000119f5c2': automation.onSensorHtEvent,
        '158d00010def50': automation.onSwitchEvent,
        '158d00010f3694': automation.onMotionEvent,
        '158d000111a168': automation.onDoorEvent,
        '158d000183525f': automation.onDoorEvent,
    }

    runLoop(rules, automation.onTimer, 60*5)
