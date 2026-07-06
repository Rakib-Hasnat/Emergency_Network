# Emergency Communication Network

A local emergency alert system that works without internet access. Three
ESP32 boards act as Wi-Fi access points and proxy traffic to a central
Raspberry Pi running a Flask server — phones connect to any ESP32 and can
send alerts, view the live feed, and comment, all over a local network.

## Architecture

```
 Phone ──Wi-Fi──▶ ESP32 (AP+STA) ──Wi-Fi──▶ Raspberry Pi (EmergencyPi hotspot)
                                              │
                                        Flask server :5000
```

- Each ESP32 runs in AP+STA mode: it broadcasts its own network for phones
  (`EmergencyNet_1/2/3`) and connects to the Pi as a client, proxying every
  request between the two.
- If an ESP32 loses connection to the Pi, it automatically reconnects on
  its own — a self-healing star topology, not a mesh network.
- The Pi is the single source of truth: it stores alerts, comments, node
  heartbeat status, and (for Node 1 only) battery telemetry.

## Setup

- **Pi side**: see [`Pi_part/docs/`](./Pi_part/docs/) — router/hotspot
  setup, Flask environment, and how to run it.
- **ESP32 side**: see [`Esp_32_program/FLASHING.md`](./Esp_32_program/FLASHING.md)
  — one shared `main.c`, flashed three times with a different `NODE_ID`
  each time.

## Optional: AI-generated advice

The `/ai-advice` endpoint calls a local [Ollama](https://ollama.com) server
(`qwen2:0.5b` model) to generate short response advice per alert. This is
optional — the rest of the system works without it. To enable it, install
Ollama on the Pi and run `ollama pull qwen2:0.5b` before starting Flask.

## Notes

- Default AP/hotspot password is `emergency123` — change this before any
  real deployment.
- Only Node 1 has the battery-monitoring circuit (10kΩ+10kΩ divider on
  GPIO34); Nodes 2 and 3 run the same firmware without it.
