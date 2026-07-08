import json
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
import psycopg
from fastapi import FastAPI, HTTPException, Query

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/industrial_telemetry")
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "industrial/machines/+/telemetry")


def db_connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def wait_for_database(max_attempts: int = 30) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            with db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            print("Database connection ready", flush=True)
            return
        except Exception as exc:
            print(f"Waiting for PostgreSQL ({attempt}/{max_attempts}): {exc}", flush=True)
            time.sleep(2)
    raise RuntimeError("PostgreSQL was not ready after retrying")


def init_database() -> None:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_readings (
                    id SERIAL PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    temperature DOUBLE PRECISION NOT NULL,
                    vibration DOUBLE PRECISION NOT NULL,
                    rpm INTEGER NOT NULL,
                    power_kw DOUBLE PRECISION NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    alert_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    acknowledged BOOLEAN DEFAULT FALSE
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_machine_time ON telemetry_readings(machine_id, timestamp DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(machine_id, alert_type, acknowledged)")
        conn.commit()
    print("Database tables ready", flush=True)


def parse_timestamp(value: str) -> datetime:
    cleaned = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(cleaned)
    return parsed.replace(tzinfo=None)


def rows_to_dicts(rows: list[tuple[Any, ...]], columns: list[str]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


def create_alert_if_needed(conn: psycopg.Connection, machine_id: str, timestamp: datetime, alert_type: str, message: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM alerts
            WHERE machine_id = %s AND alert_type = %s AND acknowledged = FALSE
            LIMIT 1
            """,
            (machine_id, alert_type),
        )
        existing = cur.fetchone()
        if existing:
            return
        cur.execute(
            """
            INSERT INTO alerts (machine_id, timestamp, alert_type, message, severity, acknowledged)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            """,
            (machine_id, timestamp, alert_type, message, "CRITICAL"),
        )
        print(f"ALERT {machine_id} {alert_type}: {message}", flush=True)


def apply_anomaly_rules(conn: psycopg.Connection, reading: dict[str, Any], timestamp: datetime) -> None:
    machine_id = reading["machine_id"]
    if reading["temperature"] >= 80:
        create_alert_if_needed(conn, machine_id, timestamp, "CRITICAL_OVERHEAT", "Temperature crossed 80C threshold")
    if reading["vibration"] >= 0.9:
        create_alert_if_needed(conn, machine_id, timestamp, "CRITICAL_VIBRATION", "Vibration crossed 0.9 threshold")
    if reading["power_kw"] >= 8:
        create_alert_if_needed(conn, machine_id, timestamp, "HIGH_POWER_USAGE", "Power usage crossed 8kW threshold")


def store_telemetry(reading: dict[str, Any]) -> None:
    timestamp = parse_timestamp(reading["timestamp"])
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry_readings
                    (machine_id, timestamp, temperature, vibration, rpm, power_kw)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (reading["machine_id"], timestamp, reading["temperature"], reading["vibration"], reading["rpm"], reading["power_kw"]),
            )
            apply_anomaly_rules(conn, reading, timestamp)
        conn.commit()
    print(
        f"Stored {reading['machine_id']} -> temp={reading['temperature']} "
        f"vibration={reading['vibration']} rpm={reading['rpm']} power={reading['power_kw']}kW",
        flush=True,
    )


def on_connect(client: mqtt.Client, userdata: Any, flags: dict[str, Any], reason_code: int, properties: Any = None) -> None:
    if reason_code == 0:
        print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}", flush=True)
        client.subscribe(MQTT_TOPIC)
        print(f"Subscribed to MQTT topic {MQTT_TOPIC}", flush=True)
    else:
        print(f"MQTT connection failed with code {reason_code}", flush=True)


def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        store_telemetry(payload)
    except Exception as exc:
        print(f"Failed to process MQTT message on {message.topic}: {exc}", flush=True)


def run_mqtt_client() -> None:
    while True:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="industrial-backend")
            client.on_connect = on_connect
            client.on_message = on_message
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever(retry_first_connection=True)
        except Exception as exc:
            print(f"Waiting for MQTT broker: {exc}", flush=True)
            time.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_database()
    init_database()
    mqtt_thread = threading.Thread(target=run_mqtt_client, daemon=True)
    mqtt_thread.start()
    yield


app = FastAPI(
    title="Industrial Telemetry Monitor",
    description="Backend-only Industrial IoT demo using MQTT, FastAPI, and PostgreSQL.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    db_status = "OK"
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception:
        db_status = "ERROR"
    return {"status": "OK" if db_status == "OK" else "DEGRADED", "database": db_status}


@app.get("/machines")
def get_machines() -> list[dict[str, str]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (machine_id)
                    machine_id, temperature, vibration, power_kw
                FROM telemetry_readings
                ORDER BY machine_id, timestamp DESC
                """
            )
            latest_rows = cur.fetchall()
            cur.execute("SELECT DISTINCT machine_id FROM alerts WHERE acknowledged = FALSE AND severity = 'CRITICAL'")
            critical_machines = {row[0] for row in cur.fetchall()}

    machines = []
    for machine_id, temperature, vibration, power_kw in latest_rows:
        if machine_id in critical_machines:
            status = "Critical"
        elif temperature >= 75 or vibration >= 0.75 or power_kw >= 7:
            status = "Warning"
        else:
            status = "Healthy"
        machines.append({"machine_id": machine_id, "status": status})
    return machines


@app.get("/machines/{machine_id}/latest")
def get_latest(machine_id: str) -> dict[str, Any]:
    columns = ["id", "machine_id", "timestamp", "temperature", "vibration", "rpm", "power_kw"]
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, machine_id, timestamp, temperature, vibration, rpm, power_kw
                FROM telemetry_readings
                WHERE machine_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (machine_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Machine has no telemetry yet")
    return dict(zip(columns, row))


@app.get("/machines/{machine_id}/telemetry")
def get_telemetry(machine_id: str, limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
    columns = ["id", "machine_id", "timestamp", "temperature", "vibration", "rpm", "power_kw"]
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, machine_id, timestamp, temperature, vibration, rpm, power_kw
                FROM telemetry_readings
                WHERE machine_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (machine_id, limit),
            )
            rows = cur.fetchall()
    return rows_to_dicts(rows, columns)


@app.get("/alerts")
def get_alerts() -> list[dict[str, Any]]:
    columns = ["id", "machine_id", "timestamp", "alert_type", "message", "severity", "acknowledged"]
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, machine_id, timestamp, alert_type, message, severity, acknowledged
                FROM alerts
                ORDER BY timestamp DESC
                """
            )
            rows = cur.fetchall()
    return rows_to_dicts(rows, columns)


@app.get("/alerts/active")
def get_active_alerts() -> list[dict[str, Any]]:
    columns = ["id", "machine_id", "timestamp", "alert_type", "message", "severity", "acknowledged"]
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, machine_id, timestamp, alert_type, message, severity, acknowledged
                FROM alerts
                WHERE acknowledged = FALSE
                ORDER BY timestamp DESC
                """
            )
            rows = cur.fetchall()
    return rows_to_dicts(rows, columns)


@app.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int) -> dict[str, Any]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alerts
                SET acknowledged = TRUE
                WHERE id = %s
                RETURNING id, machine_id, alert_type, acknowledged
                """,
                (alert_id,),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"id": row[0], "machine_id": row[1], "alert_type": row[2], "acknowledged": row[3]}
