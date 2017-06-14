from __future__ import print_function

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor, task
import json

MULTICAST_IP = '224.0.0.50'
MULTICAST_PORT = 4321

def json_beauti(json_data):
    return json.dumps(json_data, indent=4)

class Device(object):

    def __init__(self, device_id):
        self.device_id = device_id

    def onHeartBeat(self, data):
        pass

    def onReport(self, data):
        pass

    def onReadAck(self, data):
        pass


class XMSensorHt(Device):

    model = 'sensor_ht'

    def __init__(self, device_id):
        super(XMSensorHt, self).__init__(device_id)
        self.humidity = 0.0
        self.temperature = 0.0
        self.battery = 100

    def onReadAck(self, data):
        self.humidity = int(data['humidity'])/100.0
        self.temperature = int(data['temperature'])/100.0

    def onReport(self, data):
        if 'humidity' in data:
            self.humidity = int(data['humidity'])/100.0
        if 'temperature' in data:
            self.temperature = int(data['temperature'])/100.0
        self.battery = data.get('battery', self.battery)

    def __str__(self):
        return '%s [%s]: humidity: %d%%, temperature: %d C' %\
            (self.model, self.device_id, self.humidity, self.temperature)


class XMSensorStatus(Device):

    def __init__(self, device_id):
        super(XMSensorStatus, self).__init__(device_id)
        self.battery = 100
        self.status = None

    def onReadAck(self, data):
        self.status = data.get('status', self.status)

    def onReport(self, data):
        self.battery = data.get('battery', self.battery)

    def onHeartBeat(self, data):
        self.status = data['status']

    def __str__(self):
        return '%s [%s][%d%%]: %s' % (self.model, self.device_id, self.battery, self.status)


class XMSensorMagnet(XMSensorStatus):

    model = 'magnet'


class XMSensorMotion(XMSensorStatus):

    model = 'motion'

    def onReport(self, data):
        super(XMSensorStatus, self).onReport(data)


class XMSensorSwitch(XMSensorStatus):

    model = 'switch'


SUB_DEVICE_MAP = {
    XMSensorHt.model: XMSensorHt,
    XMSensorMagnet.model: XMSensorMagnet,
    XMSensorMotion.model: XMSensorMotion,
    XMSensorSwitch.model: XMSensorSwitch,
}


class XMGateway(Device):

    model = 'gateway'

    def __init__(self, ip, port, transport, device_id):
        super(XMGateway, self).__init__(device_id)
        self.ip = ip
        self.port = port
        self.transport = transport
        self.device_lst = []

    def getDevices(self):
        data = b'{"cmd":"get_id_list"}'
        self.sendCmd(data)

    def readDevice(self, device_id):
        data = '{"cmd":"read","sid":"%s"}' % device_id
        self.sendCmd(data)

    def sendCmd(self, data):
        print('send cmd: %s to %s:%s' % (data, self.ip, self.port))
        self.transport.write(data, (self.ip, self.port))

    def addDevices(self, device_lst):
        self.device_lst = device_lst

    def readDevices(self):
        for device_id in self.device_lst:
            self.readDevice(device_id)

    def __str__(self):
        return '%s [%s] %s:%d' % (self.model, self.device_id, self.ip, self.port)


class XMProtocol(DatagramProtocol):

    def __init__(self):
        self.gateway = {}
        self.sub_device = {}
        self.lc = task.LoopingCall(self.onTimer)

    def onTimer(self):
        if len(self.gateway) == 0:
            self.searchGateway()

    def startProtocol(self):
        self.transport.joinGroup(MULTICAST_IP)
        self.searchGateway()
        self.lc.start(1)

    def searchGateway(self):
        data = b'{"cmd":"whois"}'
        print('finding gateway: %s ...' % data)
        self.transport.write(data, (MULTICAST_IP, MULTICAST_PORT))

    def getSubDevice(self, device_id, model):
        if device_id in self.sub_device:
            if self.sub_device[device_id].model == model:
                return self.sub_device[device_id]
            else:
                print('model of %s not match, %s, %s' % device_id, sub_device.model, model)
        else:
            if model in SUB_DEVICE_MAP:
                model_class = SUB_DEVICE_MAP[model]
                sub_device = model_class(device_id)
                self.sub_device[device_id] = sub_device
                return sub_device
            else:
                print('model not found: %s' % model)
                return None

    def datagramReceived(self, data, addr):
        data = data.replace('"[', '[').replace(']"', ']').\
            replace('"{', '{').replace('}"', '}').\
            replace('\\"','"')
        json_data = json.loads(data)
        print('\n=====>> received:\n%s\n' % json_beauti(json_data))

        self.parseCmdData(json_data)

    def onReadAck(self, json_data):
        sub_device = self.getSubDevice(json_data['sid'], json_data['model'])
        if sub_device:
            sub_device.onReadAck(json_data['data'])

    def onHeartBeat(self, json_data):
        device_id = json_data['sid']
        device_model = json_data['model']
        if device_id in self.gateway:
            self.gateway[device_id].onHeartBeat(json_data['data'])
        else:
            sub_device = self.getSubDevice(device_id, device_model)
            if sub_device:
                sub_device.onHeartBeat(json_data['data'])

    def onReport(self, json_data):
        sub_device = self.getSubDevice(json_data['sid'], json_data['model'])
        if sub_device:
            sub_device.onReport(json_data['data'])

    def parseCmdData(self, json_data):
        if 'data' in json_data and 'error' in json_data['data']:
            print(json_data['data']['error'])

        cmd = json_data['cmd']

        if cmd == 'iam' and json_data['model'] == 'gateway':
            device_id = json_data['sid']
            if device_id not in self.gateway:
                gateway = XMGateway(json_data['ip'], int(json_data['port']), self.transport, device_id)
                self.gateway[device_id] = gateway
                print('gateway found: %s' % gateway)
                gateway.getDevices()
        elif cmd == 'get_id_list_ack':
            device_id = json_data['sid']
            if device_id in self.gateway:
                gateway = self.gateway[device_id]
                gateway.addDevices(json_data['data'])
                gateway.readDevices()
        elif cmd == 'read_ack':
            self.onReadAck(json_data)
        elif cmd == 'heartbeat':
            self.onHeartBeat(json_data)
        elif cmd == 'report':
            self.onReport(json_data)


if __name__ == '__main__':
    reactor.listenMulticast(9898, XMProtocol(), listenMultiple=True)
    reactor.run()
