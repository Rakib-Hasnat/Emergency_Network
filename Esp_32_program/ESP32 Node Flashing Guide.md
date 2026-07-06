# ESP32 Node Flashing Guide

This project uses **one shared `main.c`** for all three nodes. There is no
per-node source file — you flash the same code three times, changing one
line each time.

## Before every flash

Open `main/main.c` and change this line near the top:

```c
#define NODE_ID  2   // <-- change to 1, 2, or 3
```

| NODE_ID | AP SSID          | AP IP           | Battery monitor |
|---------|------------------|-----------------|------------------|
| 1       | EmergencyNet_1   | 192.168.10.1    | Yes (GPIO34)     |
| 2       | EmergencyNet_2   | 192.168.11.1    | No               |
| 3       | EmergencyNet_3   | 192.168.12.1    | No               |

Everything else (Pi SSID/password, reconnect logic, HTTP proxy) is identical
across nodes — only `NODE_ID` changes.

## Build & flash

```
idf.py set-target esp32
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

Replace `/dev/ttyUSB0` with the actual port (`COM3`, etc. on Windows).
Repeat for all three boards, changing `NODE_ID` and reflashing each time.

## Required CMakeLists components

`main/CMakeLists.txt` must list these as `REQUIRES` (or `PRIV_REQUIRES`) for
the code to compile:

```
esp_wifi esp_event nvs_flash esp_netif esp_http_server esp_http_client esp_adc
```

I have not seen the actual contents of your `CMakeLists.txt` files, so I
can't confirm they already include this — check manually before building on
a fresh clone.

## Battery wiring (Node 1 only)

- GPIO34 (ADC1 channel 6)
- 10kΩ + 10kΩ voltage divider from battery+ to GND, midpoint to GPIO34
- Divider halves the voltage, so the code multiplies the ADC reading by 2
  to recover actual battery voltage
- Nodes 2 and 3 have no divider circuit and must be flashed with
  `NODE_ID` set to 2 or 3 so `BATTERY_ENABLE` is 0 — flashing Node 1's
  config onto a board with no divider will just read a floating/incorrect
  voltage on GPIO34

## Known gotcha

The ESP32's Wi-Fi channel must match the Pi's `hostapd.conf` channel
setting exactly, or the STA side will scan indefinitely and never connect
to the Pi. Check `channel=` in `hostapd.conf` against whatever channel your
router setup ends up on.
