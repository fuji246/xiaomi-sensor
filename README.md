# xiaomi-sensor

python library to interact with Xiaomi Smart Home gateway and sensors (currently includes magnet sensor, motion sensor, temperature and humidity sensor).

- sensor.py : interaction with Xiaomi Smart Home

- automation.py: automation example code (the settings.py is not uploaded) to control devices like fan, humidifier, air purifier, light based on the sensors values via [ifttt](https://ifttt.com/) and [gethook](http://www.gethook.io/).

Trying to keep the code size minimal and simple to use, the sensor.py has about 300 lines of code, and automation.py has about 160 lines of code, and hopefully self-explained.


```
    automation = Automation()
    rules = {
        # subdevice_id : callback
        'f0b429b442b1': automation.onGatewayEvent,
        '158d000119f5c2': automation.onSensorHtEvent,
        '158d00010def50': automation.onSwitchEvent,
        '158d00010f3694': automation.onMotionEvent,
    }

    runLoop(rules, automation.onTimer)
```
