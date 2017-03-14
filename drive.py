import argparse
import base64
import json
from io import BytesIO

import eventlet.wsgi
import numpy as np
import socketio
from PIL import Image
from flask import Flask
from keras.models import model_from_json

from model import CROPPING, IMG_SIZE
from utils import resize_image, crop_image

sio = socketio.Server()
app = Flask(__name__)
model = None
pos_threshold = 0.1
last_pos = np.array([0., 0., 0.])
frames_not_moved = 0

@sio.on('telemetry')
def telemetry(sid, data):
    fr_wheel = data["fr_wheel"] == "True"
    fl_wheel = data["fl_wheel"] == "True"
    br_wheel = data["br_wheel"] == "True"
    bl_wheel = data["bl_wheel"] == "True"

    if not fr_wheel and not fl_wheel and not br_wheel and not bl_wheel:
        send_reset()
        return

    global frames_not_moved
    global last_pos
    global pos_threshold
    pos = np.array([float(data["px"]), float(data["py"]), float(data["pz"])])
    pos_dif = np.abs(last_pos - pos)
    if pos_dif.max() < pos_threshold:
        frames_not_moved += 1
    else:
        frames_not_moved = 0
    last_pos = pos

    if frames_not_moved > 5:
        frames_not_moved = 0
        send_reset()
        return

    # The current steering angle of the car
    steering_angle = data["steering_angle"]
    # The current throttle of the car
    throttle = data["throttle"]
    # The current speed of the car
    speed = data["speed"]

    # The current image from the center camera of the car
    imgString = data["image"]
    image = Image.open(BytesIO(base64.b64decode(imgString)))
    image_array = np.asarray(image)
    image_resized = resize_image(image_array, IMG_SIZE)
    image_norm = image_resized / 127.5 - 1.
    image_cropped = crop_image(image_norm, CROPPING)

    transformed_image_array = image_cropped[None, :, :, :]

    # This model currently assumes that the features of the model are just the images. Feel free to change this.
    steering_angle = float(model.predict(transformed_image_array, batch_size=1))
    # The driving model currently just outputs a constant throttle. Feel free to edit this.
    throttle = 1.
    print(steering_angle, throttle)
    send_control(steering_angle, throttle)


@sio.on('connect')
def connect(sid, environ):
    print("connect ", sid)
    send_control(0, 0)


def send_control(steering_angle, throttle):
    sio.emit("steer", data={
        'steering_angle': steering_angle.__str__(),
        'throttle': throttle.__str__()
    }, skip_sid=True)


def send_reset():
    sio.emit("reset", data={}, skip_sid=True)


if __name__ == '__main__':
    print("Initialisation started")

    parser = argparse.ArgumentParser(description='Remote Driving')
    parser.add_argument('model', type=str,
                        help='Path to model definition json. Model weights should be on the same path.')
    args = parser.parse_args()

    print("Loading model")
    with open(args.model, 'r') as jfile:
        model = model_from_json(json.load(jfile))

    print("Compiling model")
    model.compile("adam", "mse")
    weights_file = args.model.replace('json', 'h5')
    model.load_weights(weights_file)

    # wrap Flask application with engineio's middleware
    app = socketio.Middleware(sio, app)

    # deploy as an eventlet WSGI server
    eventlet.wsgi.server(eventlet.listen(('', 4567)), app)

    print("Initialisation complete")
