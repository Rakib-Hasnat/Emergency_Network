# Safe Manual AP Startup Sequence

Run these one by one, every time you boot.

**1. Check Wi-Fi radio status**
```
rfkill list
```
Expected output:
```
0: phy0: Wireless LAN
    Soft blocked: no
    Hard blocked: no
```

**2. Unblock Wi-Fi radio**
```
sudo rfkill unblock all
```
Check again with `rfkill list`, you should see the same "no / no" output.

**3. Stop conflicting services**
```
sudo systemctl stop wpa_supplicant
sudo systemctl stop dhcpcd
```
Ignore "unit not loaded" messages, they are harmless.

**4. Reset the interface**
```
sudo ip addr flush dev wlan0
sudo ip link set wlan0 down
sudo ip link set wlan0 up
```

**5. Assign static IP to AP interface**
```
sudo ip addr add 192.168.4.1/24 dev wlan0
```

**6. Ensure DHCP server is running**
```
sudo systemctl restart dnsmasq
```

**7. Start hostapd**
```
sudo hostapd /etc/hostapd/hostapd.conf
```

Expected terminal output when a client connects:
```
wlan0: interface state UNINITIALIZED->COUNTRY_UPDATE
wlan0: interface state COUNTRY_UPDATE->ENABLED
wlan0: AP-ENABLED
wlan0: STA c6:36:08:04:0f:46 IEEE 802.11: associated
wlan0: AP-STA-CONNECTED c6:36:08:04:0f:46
wlan0: STA c6:36:08:04:0f:46 WPA: pairwise key handshake completed (RSN)
wlan0: EAPOL-4WAY-HS-COMPLETED c6:36:08:04:0f:46
```
