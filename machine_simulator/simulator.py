import json
import os
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "industrial/machines")
MACHINE_IDS = [f"MACHINE-{number}" for number in range(1, 6)]


def connect_with_retry() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="industrial-machine-simulator")
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_start()
            print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}", flush=True)
            return client
        except Exception as exc:
            print(f"Waiting for MQTT broker: {exc}", flush=True)
            time.sleep(2)


def generate_reading(machine_id: str) -> dict:
    temperature = round(random.uniform(58, 74), 1)
    vibration = round(random.uniform(0.22, 0.62), 2)
    rpm = random.randint(1320, 1520)
    power_kw = round(random.uniform(3.8, 6.3), 1)

    anomaly_roll = random.random()
    if anomaly_roll < 0.08:
        temperature = round(random.uniform(80, 92), 1)
    elif anomaly_roll < 0.14:
        vibration = round(random.uniform(0.9, 1.2), 2)
    elif anomaly_roll < 0.20:
        power_kw = round(random.uniform(8, 10.5), 1)

    return {
        "machine_id": machine_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature": temperature,
        "vibration": vibration,
        "rpm": rpm,
        "power_kw": power_kw,
    }


def main() -> None:
    client = connect_with_retry()
    while True:
        for machine_id in MACHINE_IDS:
            reading = generate_reading(machine_id)
            topic = f"{MQTT_TOPIC_PREFIX}/{machine_id}/telemetry"
            client.publish(topic, json.dumps(reading), qos=0)
            print(
                f"{machine_id} -> temp={reading['temperature']} "
                f"vibration={reading['vibration']} rpm={reading['rpm']} "
                f"power={reading['power_kw']}kW",
                flush=True,
            )
        time.sleep(2)


if __name__ == "__main__":
    main()
