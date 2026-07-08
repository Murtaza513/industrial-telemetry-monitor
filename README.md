# Industrial Telemetry Monitor

Industrial Telemetry Monitor is a backend-only Industrial IoT demo. It simulates factory machines publishing telemetry over MQTT, ingests that data with a FastAPI backend, stores readings in PostgreSQL, detects simple anomalies, and exposes the result through Swagger, REST APIs, logs, and a CLI demo.

This is intentionally small and interview-demo friendly. There is no frontend, authentication, cloud deployment, Kubernetes, Kafka, RabbitMQ, TimescaleDB, or complex machine learning.

## Demo Video

Watch the project demo on YouTube:

[Industrial Telemetry Monitor Demo](https://youtu.be/V-h26fL3gwU)

## Architecture

```text
Machine Simulator -> MQTT Broker -> FastAPI Backend -> PostgreSQL
                                           |
                                           v
                                Swagger Docs / CLI Demo / Logs
```

## Tech Stack

- Python FastAPI backend
- paho-mqtt MQTT client
- Eclipse Mosquitto MQTT broker
- PostgreSQL database
- Python requests CLI client
- Docker Compose local deployment

## Run the System

From this project folder:

```powershell
docker compose up --build
```

The simulator starts automatically and publishes telemetry for 5 machines every 2 seconds.

Open Swagger docs:

```text
http://localhost:8000/docs
```

## CLI Demo

In another terminal, run:

```powershell
python demo_client.py
```

You can also run it through Docker Compose:

```powershell
docker compose --profile demo run --rm demo-client
```

Example output:

```text
Industrial Telemetry Monitor - CLI Demo

System health: OK | database: OK

Machines:
- MACHINE-1: Healthy
- MACHINE-2: Warning
- MACHINE-3: Critical

Latest telemetry:
MACHINE-1 | temp=64.2C | vibration=0.31 | rpm=1430 | power=4.8kW
MACHINE-2 | temp=76.5C | vibration=0.42 | rpm=1390 | power=5.2kW
MACHINE-3 | temp=86.7C | vibration=0.55 | rpm=1510 | power=6.1kW

Active alerts:
[CRITICAL] MACHINE-3 - Temperature crossed 80C threshold (CRITICAL_OVERHEAT)
```

## Useful API Commands

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/machines
curl http://localhost:8000/alerts
curl http://localhost:8000/alerts/active
curl http://localhost:8000/machines/MACHINE-1/latest
curl "http://localhost:8000/machines/MACHINE-1/telemetry?limit=20"
```

Acknowledge an alert:

```powershell
curl -X POST http://localhost:8000/alerts/1/acknowledge
```

## API Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Backend and database status |
| GET | `/machines` | Machines seen so far with calculated status |
| GET | `/machines/{machine_id}/latest` | Latest telemetry for one machine |
| GET | `/machines/{machine_id}/telemetry?limit=20` | Recent telemetry for one machine |
| GET | `/alerts` | All alerts, newest first |
| GET | `/alerts/active` | Unacknowledged alerts only |
| POST | `/alerts/{alert_id}/acknowledge` | Mark an alert as acknowledged |

## Database Inspection

Connect to PostgreSQL inside the container:

```powershell
docker exec -it industrial-postgres psql -U postgres -d industrial_telemetry
```

Useful SQL:

```sql
SELECT * FROM telemetry_readings ORDER BY timestamp DESC LIMIT 10;
SELECT * FROM alerts ORDER BY timestamp DESC LIMIT 10;
SELECT machine_id, COUNT(*) FROM telemetry_readings GROUP BY machine_id;
```

## Anomaly Detection Rules

The backend creates alerts when these thresholds are crossed:

| Rule | Alert Type | Severity |
| --- | --- | --- |
| `temperature >= 80` | `CRITICAL_OVERHEAT` | `CRITICAL` |
| `vibration >= 0.9` | `CRITICAL_VIBRATION` | `CRITICAL` |
| `power_kw >= 8` | `HIGH_POWER_USAGE` | `CRITICAL` |

To avoid noisy duplicates, the backend does not create another active alert for the same machine and alert type while an existing one is still unacknowledged.

Machine status is calculated as:

- `Critical` if the machine has any active critical alert.
- `Warning` if latest temperature is at least 75, vibration is at least 0.75, or power usage is at least 7kW.
- `Healthy` otherwise.

## Interview Demo Flow

1. Start the system:

   ```powershell
   docker compose up --build
   ```

2. Point out the logs:
   - `machine-simulator` publishes realistic machine telemetry.
   - `backend` consumes MQTT messages and stores readings.
   - alerts are printed when abnormal values appear.

3. Open Swagger:

   ```text
   http://localhost:8000/docs
   ```

4. Run the CLI summary:

   ```powershell
   python demo_client.py
   ```

5. Show a few API calls:

   ```powershell
   curl http://localhost:8000/health
   curl http://localhost:8000/machines
   curl http://localhost:8000/alerts/active
   ```

6. Inspect stored data:

   ```powershell
   docker exec -it industrial-postgres psql -U postgres -d industrial_telemetry
   ```
