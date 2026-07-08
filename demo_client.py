import os
from typing import Any

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def get_json(path: str) -> Any:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=5)
    response.raise_for_status()
    return response.json()


def print_health() -> None:
    health = get_json("/health")
    print(f"System health: {health.get('status')} | database: {health.get('database')}")


def print_machines(machines: list[dict[str, Any]]) -> None:
    print("\nMachines:")
    if not machines:
        print("- No machines seen yet. Wait a few seconds for telemetry.")
        return
    for machine in machines:
        print(f"- {machine['machine_id']}: {machine['status']}")


def print_latest_telemetry(machines: list[dict[str, Any]]) -> None:
    print("\nLatest telemetry:")
    if not machines:
        print("- No telemetry available yet.")
        return
    for machine in machines:
        machine_id = machine["machine_id"]
        try:
            latest = get_json(f"/machines/{machine_id}/latest")
            print(
                f"{machine_id} | temp={latest['temperature']}C | "
                f"vibration={latest['vibration']} | rpm={latest['rpm']} | "
                f"power={latest['power_kw']}kW"
            )
        except requests.HTTPError:
            print(f"{machine_id} | no telemetry yet")


def print_active_alerts() -> None:
    alerts = get_json("/alerts/active")
    print("\nActive alerts:")
    if not alerts:
        print("- No active alerts")
        return
    for alert in alerts:
        print(f"[{alert['severity']}] {alert['machine_id']} - {alert['message']} ({alert['alert_type']})")


def main() -> None:
    print("Industrial Telemetry Monitor - CLI Demo\n")
    print_health()
    machines = get_json("/machines")
    print_machines(machines)
    print_latest_telemetry(machines)
    print_active_alerts()


if __name__ == "__main__":
    try:
        main()
    except requests.ConnectionError:
        print(f"Could not connect to backend at {API_BASE_URL}. Start it with: docker compose up --build")
    except requests.HTTPError as exc:
        print(f"API request failed: {exc}")
