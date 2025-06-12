

import time
import serial
import busio
from board import SCL, SDA
import adafruit_fingerprint as Adafruit_Fingerprint
from firebase_admin import firestore
from firebase_utils import db

from adafruit_pca9685 import PCA9685
from adafruit_motor.servo import Servo
from adafruit_servokit import ServoKit  # For GoBILDA

# ----- Servo Setup -----

# Custom Inverted Servo class
class InvertedServo(Servo):
    @property
    def angle(self):
        raw = super().angle
        return 139 - raw if raw is not None else None

    @angle.setter
    def angle(self, value):
        value = max(0, min(139, value))
        super(InvertedServo, self.__class__).angle.fset(self, 139 - value)

# I2C and PCA9685 setup
i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c)
pca.frequency = 50

# Servo channels
axon1_channel = 5 # Normal (CW)
axon2_channel = 1 # Inverted (CCW)
gobilda_channel = 14  # GoBILDA servo channel

# Servo setup
axon1_servo = InvertedServo(pca.channels[axon1_channel], min_pulse=500, max_pulse=2500, actuation_range=139)
axon2_servo = Servo(pca.channels[axon2_channel], min_pulse=500, max_pulse=2500, actuation_range=139)
kit = ServoKit(channels=16)

def clamp(angle):
    return max(0, min(139, angle))

def smooth_servo_move(servo, start, end, step=1, delay=0.02):
    if start < end:
        for angle in range(start, end + 1, step):
            servo.angle = angle
            time.sleep(delay)
    else:
        for angle in range(start, end - 1, -step):
            servo.angle = angle
            time.sleep(delay)

def initialize_positions():
    print("Resetting to known default angles...")
    axon1_servo.angle = 0
    axon2_servo.angle = 90
    kit.servo[gobilda_channel].angle = 0
    time.sleep(2)
    print("All servos reset.")

def move_axon_servos_90_and_back():
    axon1_start = clamp(axon1_servo.angle or 0)
    axon2_start = clamp(axon2_servo.angle or 0)

    axon1_target = clamp(axon1_start - 90)  # CW
    axon2_target = clamp(axon2_start - 90)  # CCW
    print(f"Axon1 starting at {axon1_start:.1f}, Axon2 starting at {axon2_start:.1f}")

    print(f"Moving Axon1 to {axon1_target:.1f} (CW)")
    print(f"Moving Axon2 to {axon2_target:.1f} (CCW)")
    axon1_servo.angle = axon1_target
    axon2_servo.angle = axon2_target

    time.sleep(2)

    print("Rotating GoBILDA to 120 smoothly...")
    smooth_servo_move(kit.servo[gobilda_channel], 0, 120, step=2, delay=0.02)
    time.sleep(2)

    print("Returning GoBILDA to 0 smoothly...")
    smooth_servo_move(kit.servo[gobilda_channel], 120, 0, step=2, delay=0.02)
    time.sleep(2)

    print("Returning Axon servos...")
    axon1_servo.angle = axon1_start
    axon2_servo.angle = axon2_start
    print("All servos returned.")

# ----- Fingerprint Logic -----

def initialize_sensor():
    try:
        uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
        print("UART initialized successfully")
        finger = Adafruit_Fingerprint.Adafruit_Fingerprint(uart)
        print("Fingerprint sensor initialized successfully")
        return uart, finger
    except Exception as e:
        print(f"Initialization error: {e}")
        return None, None

def get_fingerprint(finger):
    print("Waiting for valid fingerprint...")
    while finger.get_image() != Adafruit_Fingerprint.OK:
        pass
    if finger.image_2_tz(1) != Adafruit_Fingerprint.OK:
        return False
    if finger.finger_search() != Adafruit_Fingerprint.OK:
        return False

    print("Fingerprint matched. Triggering door open logic.")
    return True

def enroll_fingerprint(finger, entered_password, name):
    correct_password = "securepassword"
    if entered_password != correct_password:
        print("Incorrect password. Access denied.")
        return False

    used_ids = []
    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if "id" in data:
            used_ids.append(int(data["id"]))

    next_id = min(set(range(1, 128)) - set(used_ids)) if used_ids else 1
    print(f"Enrolling fingerprint at ID {next_id}...")

    for img_num in range(1, 3):
        print(f"Place finger on sensor ({'first' if img_num == 1 else 'second'} scan)...")
        while True:
            if finger.get_image() == Adafruit_Fingerprint.OK:
                print("Image taken")
                break
            time.sleep(0.1)

        if finger.image_2_tz(img_num) != Adafruit_Fingerprint.OK:
            print("Error processing image")
            return False

        if img_num == 1:
            print("Remove finger")
            while finger.get_image() != Adafruit_Fingerprint.NOFINGER:
                time.sleep(0.1)
            print("Place the same finger again")
            time.sleep(1)

    if finger.create_model() != Adafruit_Fingerprint.OK:
        print("Failed to create fingerprint model")
        return False

    if finger.store_model(next_id) != Adafruit_Fingerprint.OK:
        print("Failed to store fingerprint model")
        return False

    db.collection("fingerprints").document(str(next_id)).set({
        "id": next_id,
        "name": name
    })

    print(f"Fingerprint enrolled successfully at ID {next_id} for {name}!")
    return True

def delete_fingerprint(finger, name_to_delete):
    found_doc = None

    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if data.get("name", "").lower() == name_to_delete.lower():
            found_doc = (doc.id, data.get("id"))
            break

    if not found_doc:
        print(f"No fingerprint found with the name '{name_to_delete}'.")
        return False

    doc_id, fingerprint_id = found_doc

    if finger.delete_model(fingerprint_id) != Adafruit_Fingerprint.OK:
        print(f"Failed to delete fingerprint with ID {fingerprint_id} from sensor.")
        return False

    db.collection("fingerprints").document(doc_id).delete()
    print(f"Deleted fingerprint '{name_to_delete}' (ID {fingerprint_id}) from sensor and Firestore.")
    return True

# ----- Door Open/Close Logic -----

door_state = {"open": False}

def open_door_if_closed():
    if door_state["open"]:
        print("Open attempt blocked: already open.")
        return False, "Door is already open."

    print("Unlocking door with Axons...")
    axon1_servo.angle = 90     # Channel 5 – CW
    axon2_servo.angle = 0      # Channel 1 – CCW
    time.sleep(3)

    print("Swinging door open (GoBILDA)...")
    smooth_servo_move(kit.servo[gobilda_channel], 0, 120, step=2, delay=0.02)
    time.sleep(1)

    door_state["open"] = True
    return True, "Door unlocked and opened."

def close_door_if_open():
    if not door_state["open"]:
        print("Close attempt blocked: already closed.")
        return False, "Door is already closed."

    print("Swinging door closed (GoBILDA)...")
    smooth_servo_move(kit.servo[gobilda_channel], 120, 0, step=2, delay=0.02)
    time.sleep(1)

    print("Locking door with Axons...")
    axon1_servo.angle = 0      # Channel 5 – CCW
    axon2_servo.angle = 90     # Channel 1 – CW
    time.sleep(3)

    door_state["open"] = False
    return True, "Door closed and locked."





'''import time
import serial
import busio
from board import SCL, SDA
import adafruit_fingerprint as Adafruit_Fingerprint
from firebase_admin import firestore
from firebase_utils import db

from adafruit_pca9685 import PCA9685
from adafruit_motor.servo import Servo
from adafruit_servokit import ServoKit  # For GoBILDA

# ----- Servo Setup -----

# Custom Inverted Servo class
class InvertedServo(Servo):
    @property
    def angle(self):
        raw = super().angle
        return 139 - raw if raw is not None else None

    @angle.setter
    def angle(self, value):
        value = max(0, min(139, value))
        super(InvertedServo, self.__class__).angle.fset(self, 139 - value)

# I2C and PCA9685 setup
i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c)
pca.frequency = 50

# Servo channels
axon1_channel = 5 # Normal (CW)
axon2_channel = 1 # Inverted (CCW)
gobilda_channel = 14  # GoBILDA servo channel

# Servo setup
axon1_servo = InvertedServo(pca.channels[axon1_channel], min_pulse=500, max_pulse=2500, actuation_range=139)
axon2_servo = Servo(pca.channels[axon2_channel], min_pulse=500, max_pulse=2500, actuation_range=139) # was inverted
kit = ServoKit(channels=16)

def clamp(angle):
    return max(0, min(139, angle))

def initialize_positions():
    print("Resetting to known default angles...")
    axon1_servo.angle = 0
    axon2_servo.angle = 90 # was 90
    kit.servo[gobilda_channel].angle = 0
    time.sleep(2)
    print("All servos reset.")

def move_axon_servos_90_and_back():
    axon1_start = clamp(axon1_servo.angle or 0)
    axon2_start = clamp(axon2_servo.angle or 0)

    axon1_target = clamp(axon1_start - 90)  # CW
    axon2_target = clamp(axon2_start - 90)  # CCW
    print(f"Axon1 starting at {axon1_start:.1f}, Axon2 starting at {axon2_start:.1f}")

    print(f"Moving Axon1 to {axon1_target:.1f} (CW)")
    print(f"Moving Axon2 to {axon2_target:.1f} (CCW)")
    axon1_servo.angle = axon1_target
    axon2_servo.angle = axon2_target

    time.sleep(2)

    print("Rotating GoBILDA to 150...")
    kit.servo[gobilda_channel].angle = 120
    time.sleep(5)

    print("Returning GoBILDA to 0...")
    kit.servo[gobilda_channel].angle = 0
    time.sleep(2)

    print("Returning Axon servos...")
    axon1_servo.angle = axon1_start
    axon2_servo.angle = axon2_start
    print("All servos returned.")

# ----- Fingerprint Logic -----

def initialize_sensor():
    try:
        uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
        print("UART initialized successfully")
        finger = Adafruit_Fingerprint.Adafruit_Fingerprint(uart)
        print("Fingerprint sensor initialized successfully")
        return uart, finger
    except Exception as e:
        print(f"Initialization error: {e}")
        return None, None

def get_fingerprint(finger):
    print("Waiting for valid fingerprint...")
    while finger.get_image() != Adafruit_Fingerprint.OK:
        pass
    if finger.image_2_tz(1) != Adafruit_Fingerprint.OK:
        return False
    if finger.finger_search() != Adafruit_Fingerprint.OK:
        return False

    print("Fingerprint matched. Triggering door open logic.")
    return True

def enroll_fingerprint(finger, entered_password, name):
    correct_password = "securepassword"
    if entered_password != correct_password:
        print("Incorrect password. Access denied.")
        return False

    used_ids = []
    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if "id" in data:
            used_ids.append(int(data["id"]))

    next_id = min(set(range(1, 128)) - set(used_ids)) if used_ids else 1
    print(f"Enrolling fingerprint at ID {next_id}...")

    for img_num in range(1, 3):
        print(f"Place finger on sensor ({'first' if img_num == 1 else 'second'} scan)...")
        while True:
            if finger.get_image() == Adafruit_Fingerprint.OK:
                print("Image taken")
                break
            time.sleep(0.1)

        if finger.image_2_tz(img_num) != Adafruit_Fingerprint.OK:
            print("Error processing image")
            return False

        if img_num == 1:
            print("Remove finger")
            while finger.get_image() != Adafruit_Fingerprint.NOFINGER:
                time.sleep(0.1)
            print("Place the same finger again")
            time.sleep(1)

    if finger.create_model() != Adafruit_Fingerprint.OK:
        print("Failed to create fingerprint model")
        return False

    if finger.store_model(next_id) != Adafruit_Fingerprint.OK:
        print("Failed to store fingerprint model")
        return False

    db.collection("fingerprints").document(str(next_id)).set({
        "id": next_id,
        "name": name
    })

    print(f"Fingerprint enrolled successfully at ID {next_id} for {name}!")
    return True

def delete_fingerprint(finger, name_to_delete):
    found_doc = None

    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if data.get("name", "").lower() == name_to_delete.lower():
            found_doc = (doc.id, data.get("id"))
            break

    if not found_doc:
        print(f"No fingerprint found with the name '{name_to_delete}'.")
        return False

    doc_id, fingerprint_id = found_doc

    if finger.delete_model(fingerprint_id) != Adafruit_Fingerprint.OK:
        print(f"Failed to delete fingerprint with ID {fingerprint_id} from sensor.")
        return False

    db.collection("fingerprints").document(doc_id).delete()
    print(f"Deleted fingerprint '{name_to_delete}' (ID {fingerprint_id}) from sensor and Firestore.")
    return True

# ----- Door Open/Close Logic -----

door_state = {"open": False}

def open_door_if_closed():
    if door_state["open"]:
        print("Open attempt blocked: already open.")
        return False, "Door is already open."

    print("Unlocking door with Axons...")
    axon1_servo.angle = 90     # Channel 5 – CW
    axon2_servo.angle = 0      # Channel 1 – CCW
    time.sleep(3)

    print("Swinging door open (GoBILDA)...")
    kit.servo[gobilda_channel].angle = 120
    time.sleep(3)

    door_state["open"] = True
    return True, "Door unlocked and opened."

def close_door_if_open():
    if not door_state["open"]:
        print("Close attempt blocked: already closed.")
        return False, "Door is already closed."

    print("Swinging door closed (GoBILDA)...")
    kit.servo[gobilda_channel].angle = 0
    time.sleep(3)

    print("Locking door with Axons...")
    axon1_servo.angle = 0      # Channel 5 – CCW
    axon2_servo.angle = 90     # Channel 1 – CW
    time.sleep(3)

    door_state["open"] = False
    return True, "Door closed and locked."


'''




'''import time
import serial
import busio
from board import SCL, SDA
import adafruit_fingerprint as Adafruit_Fingerprint
from firebase_admin import firestore
from firebase_utils import db

from adafruit_pca9685 import PCA9685
from adafruit_motor.servo import Servo
from adafruit_servokit import ServoKit  # For GoBILDA

# ----- Servo Setup -----

# Custom Inverted Servo class
class InvertedServo(Servo):
    @property
    def angle(self):
        raw = super().angle
        return 139 - raw if raw is not None else None

    @angle.setter
    def angle(self, value):
        value = max(0, min(139, value))
        super(InvertedServo, self.__class__).angle.fset(self, 139 - value)

# I2C and PCA9685 setup
i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c)
pca.frequency = 50

# Servo channels
axon1_channel = 5 # Normal (CW)
axon2_channel = 1 # Inverted (CCW)
gobilda_channel = 14  # GoBILDA servo channel

# Servo setup
axon1_servo = Servo(pca.channels[axon1_channel], min_pulse=500, max_pulse=2500, actuation_range=139)
axon2_servo = Servo(pca.channels[axon2_channel], min_pulse=500, max_pulse=2500, actuation_range=139) # was inverted
kit = ServoKit(channels=16)

def clamp(angle):
    return max(0, min(139, angle))

def initialize_positions():
    print("Resetting to known default angles...")
    axon1_servo.angle = 0
    axon2_servo.angle = 90 # was 90
    kit.servo[gobilda_channel].angle = 0
    time.sleep(2)
    print("All servos reset.")


def move_axon_servos_90_and_back():
    axon1_start = clamp(axon1_servo.angle or 0)
    axon2_start = clamp(axon2_servo.angle or 0)

    axon1_target = clamp(axon1_start - 90)  # CW
    axon2_target = clamp(axon2_start - 90)  # CCW
    print(f"Axon1 starting at {axon1_start:.1f}, Axon2 starting at {axon2_start:.1f}")

    print(f"Moving Axon1 to {axon1_target:.1f} (CW)")
    print(f"Moving Axon2 to {axon2_target:.1f} (CCW)")
    axon1_servo.angle = axon1_target
    axon2_servo.angle = axon2_target

    time.sleep(2)

    print("Rotating GoBILDA to 150...")
    kit.servo[gobilda_channel].angle = 120
    time.sleep(5)

    print("Returning GoBILDA to 0...")
    kit.servo[gobilda_channel].angle = 0
    time.sleep(2)

    print("Returning Axon servos...")
    axon1_servo.angle = axon1_start
    axon2_servo.angle = axon2_start
    print("All servos returned.")

# ----- Fingerprint Logic -----

def initialize_sensor():
    try:
        uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
        print("UART initialized successfully")
        finger = Adafruit_Fingerprint.Adafruit_Fingerprint(uart)
        print("Fingerprint sensor initialized successfully")
        return uart, finger
    except Exception as e:
        print(f"Initialization error: {e}")
        return None, None

def get_fingerprint(finger):
    print("Waiting for valid fingerprint...")
    while finger.get_image() != Adafruit_Fingerprint.OK:
        pass
    if finger.image_2_tz(1) != Adafruit_Fingerprint.OK:
        return False
    if finger.finger_search() != Adafruit_Fingerprint.OK:
        return False

    print("Fingerprint matched. Triggering servos.")
 
    move_axon_servos_90_and_back()

    return True
def enroll_fingerprint(finger, entered_password, name):
    correct_password = "securepassword"
    if entered_password != correct_password:
        print("Incorrect password. Access denied.")
        return False

    used_ids = []
    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if "id" in data:
            used_ids.append(int(data["id"]))

    next_id = min(set(range(1, 128)) - set(used_ids)) if used_ids else 1
    print(f"Enrolling fingerprint at ID {next_id}...")

    for img_num in range(1, 3):
        print(f"Place finger on sensor ({'first' if img_num == 1 else 'second'} scan)...")
        while True:
            if finger.get_image() == Adafruit_Fingerprint.OK:
                print("Image taken")
                break
            time.sleep(0.1)

        if finger.image_2_tz(img_num) != Adafruit_Fingerprint.OK:
            print("Error processing image")
            return False

        if img_num == 1:
            print("Remove finger")
            while finger.get_image() != Adafruit_Fingerprint.NOFINGER:
                time.sleep(0.1)
            print("Place the same finger again")
            time.sleep(1)

    if finger.create_model() != Adafruit_Fingerprint.OK:
        print("Failed to create fingerprint model")
        return False

    if finger.store_model(next_id) != Adafruit_Fingerprint.OK:
        print("Failed to store fingerprint model")
        return False

    db.collection("fingerprints").document(str(next_id)).set({
        "id": next_id,
        "name": name
    })

    print(f"Fingerprint enrolled successfully at ID {next_id} for {name}!")
    return True

def delete_fingerprint(finger, name_to_delete):
    #def delete_fingerprint(finger):
    #name_to_delete = input("Enter the name of the fingerprint to delete: ").strip()
    found_doc = None

    # Search Firestore for a document with matching name
    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if data.get("name", "").lower() == name_to_delete.lower():
            found_doc = (doc.id, data.get("id"))
            break

    if not found_doc:
        print(f"No fingerprint found with the name '{name_to_delete}'.")
        return False

    doc_id, fingerprint_id = found_doc

    # Delete from fingerprint sensor
    if finger.delete_model(fingerprint_id) != Adafruit_Fingerprint.OK:
        print(f"Failed to delete fingerprint with ID {fingerprint_id} from sensor.")
        return False

    # Delete from Firestore
    db.collection("fingerprints").document(doc_id).delete()
    print(f"Deleted fingerprint '{name_to_delete}' (ID {fingerprint_id}) from sensor and Firestore.")
    return True
'''


'''import time
import serial
import busio
from board import SCL, SDA
import adafruit_fingerprint as Adafruit_Fingerprint
from firebase_admin import firestore
from firebase_utils import db

from adafruit_pca9685 import PCA9685
from adafruit_motor.servo import Servo
from adafruit_servokit import ServoKit  # For GoBILDA

# ----- Servo Setup -----

# Custom Inverted Servo class
class InvertedServo(Servo):
    @property
    def angle(self):
        raw = super().angle
        return 139 - raw if raw is not None else None

    @angle.setter
    def angle(self, value):
        value = max(0, min(139, value))
        super(InvertedServo, self.__class__).angle.fset(self, 139 - value)

# I2C and PCA9685 setup
i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c)
pca.frequency = 50

# Servo channels
axon1_channel = 5 # Normal (CW)
axon2_channel = 1 # Inverted (CCW)
gobilda_channel = 14  # GoBILDA servo channel

# Servo setup
axon1_servo = Servo(pca.channels[axon1_channel], min_pulse=500, max_pulse=2500, actuation_range=139)
axon2_servo = Servo(pca.channels[axon2_channel], min_pulse=500, max_pulse=2500, actuation_range=139) # was inverted
kit = ServoKit(channels=16)

def clamp(angle):
    return max(0, min(139, angle))

def initialize_positions():
    print("Resetting to known default angles...")
    axon1_servo.angle = 0
    axon2_servo.angle = 90 # was 90
    kit.servo[gobilda_channel].angle = 0
    time.sleep(2)
    print("All servos reset.")



def move_axon_servos_90_and_back():
    axon1_start = clamp(axon1_servo.angle or 0)
    axon2_start = clamp(axon2_servo.angle or 0) # as 90
    
    axon1_target = clamp(axon1_start - 90)  # CW
    axon2_target = clamp(axon2_start - 90)  # CCW via inversion
    print(f"Axon1 starting at {axon1_start:.1f}, Axon2 starting at {axon2_start:.1f}")

    print(f"Moving Axon1 to {axon1_target:.1f} (CW)")
    print(f"Moving Axon2 to {axon2_target:.1f} (CCW)")
    axon1_servo.angle = axon1_target
    axon2_servo.angle = axon2_target

    time.sleep(5)

    print("Rotating GoBILDA to 180...")
    kit.servo[gobilda_channel].angle = 150

    print("Returning all servos...")
    
    kit.servo[gobilda_channel].angle = 0
    
    axon1_servo.angle = axon1_target
    axon2_servo.angle = axon2_target
    time.sleep(1)
    axon1_servo.angle = axon1_start
    axon2_servo.angle = axon2_start
    print("Servos returned.")

# ----- Fingerprint Logic -----

def initialize_sensor():
    try:
        uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
        print("UART initialized successfully")
        finger = Adafruit_Fingerprint.Adafruit_Fingerprint(uart)
        print("Fingerprint sensor initialized successfully")
        return uart, finger
    except Exception as e:
        print(f"Initialization error: {e}")
        return None, None

def get_fingerprint(finger):
    print("Waiting for valid fingerprint...")
    while finger.get_image() != Adafruit_Fingerprint.OK:
        pass
    if finger.image_2_tz(1) != Adafruit_Fingerprint.OK:
        return False
    if finger.finger_search() != Adafruit_Fingerprint.OK:
        return False

    print("Fingerprint matched. Triggering servos.")
    initialize_sensor()
    move_axon_servos_90_and_back()

    return True
def enroll_fingerprint(finger, entered_password, name):
    correct_password = "securepassword"
    if entered_password != correct_password:
        print("Incorrect password. Access denied.")
        return False

    used_ids = []
    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if "id" in data:
            used_ids.append(int(data["id"]))

    next_id = min(set(range(1, 128)) - set(used_ids)) if used_ids else 1
    print(f"Enrolling fingerprint at ID {next_id}...")

    for img_num in range(1, 3):
        print(f"Place finger on sensor ({'first' if img_num == 1 else 'second'} scan)...")
        while True:
            if finger.get_image() == Adafruit_Fingerprint.OK:
                print("Image taken")
                break
            time.sleep(0.1)

        if finger.image_2_tz(img_num) != Adafruit_Fingerprint.OK:
            print("Error processing image")
            return False

        if img_num == 1:
            print("Remove finger")
            while finger.get_image() != Adafruit_Fingerprint.NOFINGER:
                time.sleep(0.1)
            print("Place the same finger again")
            time.sleep(1)

    if finger.create_model() != Adafruit_Fingerprint.OK:
        print("Failed to create fingerprint model")
        return False

    if finger.store_model(next_id) != Adafruit_Fingerprint.OK:
        print("Failed to store fingerprint model")
        return False

    db.collection("fingerprints").document(str(next_id)).set({
        "id": next_id,
        "name": name
    })

    print(f"Fingerprint enrolled successfully at ID {next_id} for {name}!")
    return True

def delete_fingerprint(finger, name_to_delete):
    #def delete_fingerprint(finger):
    #name_to_delete = input("Enter the name of the fingerprint to delete: ").strip()
    found_doc = None

    # Search Firestore for a document with matching name
    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if data.get("name", "").lower() == name_to_delete.lower():
            found_doc = (doc.id, data.get("id"))
            break

    if not found_doc:
        print(f"No fingerprint found with the name '{name_to_delete}'.")
        return False

    doc_id, fingerprint_id = found_doc

    # Delete from fingerprint sensor
    if finger.delete_model(fingerprint_id) != Adafruit_Fingerprint.OK:
        print(f"Failed to delete fingerprint with ID {fingerprint_id} from sensor.")
        return False

    # Delete from Firestore
    db.collection("fingerprints").document(doc_id).delete()
    print(f"Deleted fingerprint '{name_to_delete}' (ID {fingerprint_id}) from sensor and Firestore.")
    return True

'''







'''import time
import serial
import adafruit_fingerprint as Adafruit_Fingerprint
from firebase_admin import firestore
from firebase_utils import db

def initialize_sensor():
    try:
        uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
        print("UART initialized successfully")
        finger = Adafruit_Fingerprint.Adafruit_Fingerprint(uart)
        print("Fingerprint sensor initialized successfully")
        return uart, finger
    except Exception as e:
        print(f"Initialization error: {e}")
        return None, None

from servo_controller import move_axon_servos_90_and_back

def get_fingerprint(finger):
    print("Waiting for valid fingerprint...")
    while finger.get_image() != Adafruit_Fingerprint.OK:
        pass
    if finger.image_2_tz(1) != Adafruit_Fingerprint.OK:
        return False
    if finger.finger_search() != Adafruit_Fingerprint.OK:
        return False

    print("Fingerprint matched. Triggering servo.")
    move_axon_servos_90_and_back()
    return True

def enroll_fingerprint(finger):
    correct_password = "securepassword"
    entered_password = input("Enter the password to enroll a new fingerprint: ")
    if entered_password != correct_password:
        print("Incorrect password. Access denied.")
        return False

    # Get currently used IDs from Firestore
    used_ids = []
    docs = db.collection("fingerprints").stream()
    for doc in docs:
        data = doc.to_dict()
        if "id" in data:
            used_ids.append(int(data["id"]))

    next_id = min(set(range(1, 128)) - set(used_ids)) if used_ids else 1
    print(f"Enrolling fingerprint at ID {next_id}...")

    for img_num in range(1, 3):
        print(f"Place finger on sensor ({'first' if img_num == 1 else 'second'} scan)...")
        while True:
            if finger.get_image() == Adafruit_Fingerprint.OK:
                print("Image taken")
                break
            time.sleep(0.1)

        if finger.image_2_tz(img_num) != Adafruit_Fingerprint.OK:
            print("Error processing image")
            return False

        if img_num == 1:
            print("Remove finger")
            while finger.get_image() != Adafruit_Fingerprint.NOFINGER:
                time.sleep(0.1)
            print("Place the same finger again")
            time.sleep(1)

    if finger.create_model() != Adafruit_Fingerprint.OK:
        print("Failed to create fingerprint model")
        return False

    if finger.store_model(next_id) != Adafruit_Fingerprint.OK:
        print("Failed to store fingerprint model")
        return False

    # Save to Firestore
    name = input("Enter a name for this fingerprint: ")
    db.collection("fingerprints").document(str(next_id)).set({
        "id": next_id,
        "name": name
    })

    print(f"Fingerprint enrolled successfully at ID {next_id} for {name}!")
    return True

def delete_fingerprint(finger):
    print("Deleting fingerprint...")
    for i in range(1, 128):
        if finger.delete_model(i) == Adafruit_Fingerprint.OK:
            # Also delete from Firestore
            db.collection("fingerprints").document(str(i)).delete()
            print(f"Deleted fingerprint ID {i} from sensor and Firestore.")
            return True
    print("No fingerprints found to delete.")
    return False
'''
