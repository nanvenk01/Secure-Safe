import time
import busio
from board import SCL, SDA
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c)
pca.frequency = 50

axon1_channel = 3
axon1_servo = servo.Servo(pca.channels[axon1_channel], min_pulse=500, max_pulse=2500)

def open_and_close_servo():
    current_angle = axon1_servo.angle or 45
    new_angle = min(current_angle + 90, 139)
    axon1_servo.angle = new_angle
    time.sleep(2)
    time.sleep(10)
    axon1_servo.angle = current_angle
    time.sleep(2)

def cleanup_servo():
    pca.deinit()
