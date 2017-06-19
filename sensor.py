from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor, task
import json
import time

MULTICAST_IP = '224.0.0.50'
MULTICAST_PORT = 4321

LOG_DIR = '/tmp/sensor.log'

import logging
logger = logging.getLogger('store')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

hdlr = logging.FileHandler(LOG_DIR)
hdlr.setFormatter(formatter)
hdlr.setLevel(logging.DEBUG)
logger.addHandler(hdlr)

console = logging.StreamHandler()
console.setFormatter(formatter)
console.setLevel(logging.INFO)
logger.addHandler(console)


def json_beauti(json_data):
    return json.dumps(json_data, indent=4)


class Event(list):
    def __call__(self, *args, **kwargs):
        for f in self:
            f(*args, **kwargs)

    def __repr__(self):
        return "Event(%s)" % list.__repr__(self)


class Device(object):

    def __init__(self, device_id):
        self.device_id = device_id
        self.battery = 100
        self.event = Event()

    def subscribe(self, callback):
        logger.debug('%s subscribe %s' % (self.device_id, callback))
        self.event.append(callback)

    def unsubscribe(self, callback):
        logger.debug('%s unsubscribe %s' % (self.device_id, callback))
        self.event.remove(callback)

    def onEvent(self):
        self.event(self)

    def onHeartBeat(self, data):
        pass

    def onReport(self, data):
        pass

    def onReadAck(self, data):
        pass


class BatteryMixin(object):

    MAX_VOLTAGE = 3300
    LOW_VOLTAGE = 2800

    def checkBattery(self, data):
        voltage = data.get('voltage', self.MAX_VOLTAGE)
        return 100 * (voltage - self.LOW_VOLTAGE) / (self.MAX_VOLTAGE - self.LOW_VOLTAGE)


class XMSensorHt(Device, BatteryMixin):

    model = 'sensor_ht'

    def __init__(self, device_id):
        super(XMSensorHt, self).__init__(device_id)
        self.humidity = 0.0
        self.temperature = 0.0

    def onReadAck(self, data):
        self.humidity = int(data['humidity'])/100.0
        self.temperature = int(data['temperature'])/100.0
        self.onEvent()

    def onReport(self, data):
        if 'humidity' in data:
            self.humidity = int(data['humidity'])/100.0
        if 'temperature' in data:
            self.temperature = int(data['temperature'])/100.0
        self.battery = self.checkBattery(data)
        self.onEvent()

    def __str__(self):
        return '%s [%s] %d%%: humidity: %d%%, temperature: %d C' %\
            (self.model, self.device_id, self.battery, self.humidity, self.temperature)


class XMSensorStatus(Device, BatteryMixin):

    def __init__(self, device_id):
        super(XMSensorStatus, self).__init__(device_id)
        self.status = None

    def onReadAck(self, data):
        self.status = data.get('status', self.status)
        self.onEvent()

    def onHeartBeat(self, data):
        self.battery = self.checkBattery(data)

    def onReport(self, data):
        self.status = data.get('status', self.status)
        self.onEvent()

    def __str__(self):
        return '%s [%s] %d%%: %s' % (self.model, self.device_id, self.battery, self.status)


class XMSensorMagnet(XMSensorStatus):

    model = 'magnet'


class XMSensorMotion(XMSensorStatus):

    model = 'motion'


class XMSensorSwitch(XMSensorStatus):

    model = 'switch'


class XMGateway(Device):

    model = 'gateway'
    min_illumination = 300
    max_illumination = 1300

    def __init__(self, device_id):
        super(XMGateway, self).__init__(device_id)
        self.device_list_ready = False
        self.rgb = ''
        self.illumination = 0

    def setTransport(self, ip, port, transport):
        self.ip = ip
        self.port = port
        self.transport = transport

    def getDevices(self):
        data = b'{"cmd":"get_id_list"}'
        self.sendCmd(data)

    def readDevice(self, device_id):
        data = '{"cmd":"read","sid":"%s"}' % device_id
        self.sendCmd(data)

    def sendCmd(self, data):
        logger.debug('send cmd: %s to %s:%s' % (data, self.ip, self.port))
        self.transport.write(data, (self.ip, self.port))

    def readDevices(self, device_lst):
        for device_id in device_lst:
            self.readDevice(device_id)

    def onGatewayLightData(self, data):
        self.rgb = str(hex(data['rgb']))[4:]
        self.illumination = int(data['illumination'])
        self.onEvent()

    def onReport(self, data):
        self.onGatewayLightData(data)

    def onReadAck(self, data):
        self.onGatewayLightData(data)

    def onDeviceList(self, data):
        self.readDevice(self.device_id)
        self.readDevices(data)
        self.device_list_ready = True

    def __str__(self):
        return '%s [%s] %s:%d, rgb: #%s, illumination: %d' % \
            (self.model, self.device_id, self.ip, self.port, self.rgb, self.illumination)


DEVICE_FACTORY_MAP = {
    XMSensorHt.model: XMSensorHt,
    XMSensorMagnet.model: XMSensorMagnet,
    XMSensorMotion.model: XMSensorMotion,
    XMSensorSwitch.model: XMSensorSwitch,
    XMGateway.model: XMGateway,
}


class XMProtocol(DatagramProtocol):

    def __init__(self, rules, timer_hook):
        self.rules = rules
        self.gateway = {}
        self.devices = {}
        self.lc = task.LoopingCall(self.onTimer)
        self.timer_hook = timer_hook

    def onTimer(self):
        if len(self.gateway) == 0:
            self.searchGateway()
        for gateway in self.gateway.values():
            if not gateway.device_list_ready:
                gateway.getDevices()
        if self.timer_hook is not None:
            self.timer_hook()

    def startProtocol(self):
        self.transport.joinGroup(MULTICAST_IP)
        self.searchGateway()
        self.lc.start(3, False)

    def searchGateway(self):
        data = b'{"cmd":"whois"}'
        logger.info('finding gateway: %s ...' % data)
        self.transport.write(data, (MULTICAST_IP, MULTICAST_PORT))

    def getOrCreateDevice(self, device_id, model):
        if device_id in self.devices:
            if self.devices[device_id].model == model:
                return self.devices[device_id]
            else:
                logger.warn('model of %s not match, %s, %s' % device_id, self.devices[device_id].model, model)
        else:
            if model in DEVICE_FACTORY_MAP:
                model_class = DEVICE_FACTORY_MAP[model]
                device = model_class(device_id)
                self.devices[device_id] = device
                if device_id in self.rules:
                    device.subscribe(self.rules[device_id])
                return device
            else:
                logger.warn('model not found: %s' % model)
                return None

    def datagramReceived(self, data, addr):
        data = data.replace('"[', '[').replace(']"', ']').\
            replace('"{', '{').replace('}"', '}').\
            replace('\\"','"')
        json_data = json.loads(data)
        logger.debug('\n=====>> received:\n%s\n' % json_beauti(json_data))

        self.parseCmdData(json_data)

    def onReadAck(self, json_data):
        device = self.getOrCreateDevice(json_data['sid'], json_data['model'])
        if device:
            device.onReadAck(json_data['data'])
            logger.info('onReadAck, device: %s' % device)

    def onHeartBeat(self, json_data):
        device = self.getOrCreateDevice(json_data['sid'], json_data['model'])
        if device:
            device.onHeartBeat(json_data['data'])

    def onReport(self, json_data):
        device = self.getOrCreateDevice(json_data['sid'], json_data['model'])
        if device:
            device.onReport(json_data['data'])

    def parseCmdData(self, json_data):
        if 'data' in json_data and 'error' in json_data['data']:
            logger.error(json_data['data']['error'])

        cmd = json_data['cmd']

        if cmd == 'iam' and json_data['model'] == 'gateway':
            device_id = json_data['sid']
            if device_id not in self.gateway:
                gateway = self.getOrCreateDevice(json_data['sid'], json_data['model'])
                gateway.setTransport(json_data['ip'], int(json_data['port']), self.transport)
                self.gateway[device_id] = gateway
                logger.info('gateway found: %s' % gateway)
                gateway.getDevices()
        elif cmd == 'get_id_list_ack':
            device_id = json_data['sid']
            if device_id in self.gateway:
                gateway = self.gateway[device_id]
                gateway.onDeviceList(json_data['data'])
        elif cmd == 'read_ack':
            self.onReadAck(json_data)
        elif cmd == 'heartbeat':
            self.onHeartBeat(json_data)
        elif cmd == 'report':
            self.onReport(json_data)


def runLoop(rules={}, timer_hook=None):
    proto = XMProtocol(rules, timer_hook)
    reactor.listenMulticast(9898, proto, listenMultiple=True)
    reactor.run()

if __name__ == '__main__':
    runLoop()

