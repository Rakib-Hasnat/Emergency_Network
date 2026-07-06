# Router / AP Setup (Raspberry Pi)

## Step 1: Install Required Software
```
sudo apt update
sudo apt install hostapd dnsmasq -y
```

## Step 2: Configure hostapd (Wi-Fi name & password)
```
sudo nano /etc/hostapd/hostapd.conf
```
Paste:
```
interface=wlan0
driver=nl80211
ssid=EmergencyPi
hw_mode=g
channel=6
country_code=BD
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_passphrase=<your-ap-password>
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
```
Save: `CTRL + X` → `Y` → `Enter`

## Step 3: Tell system where hostapd config is
```
sudo nano /etc/default/hostapd
```
Find this line, uncomment it, then edit it:
```
DAEMON_CONF="/etc/hostapd/hostapd.conf"
```

## Step 4: Configure dnsmasq (gives IP to devices)
```
sudo nano /etc/dnsmasq.conf
```
Go to the very bottom and paste:
```
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.50,255.255.255.0,24h
```

## Step 5: Set static IP for Wi-Fi (VERY IMPORTANT)
```
sudo nano /etc/dhcpcd.conf
```
Add at the bottom:
```
interface wlan0
static ip_address=192.168.4.1/24
nohook wpa_supplicant
```

## Step 6: Stop services for now (manual control)
```
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

sudo systemctl disable hostapd
sudo systemctl disable dnsmasq
```

## Step 7: Start your Wi-Fi manually (EVERY TIME YOU BOOT)

See [`ap_startup_manual.md`](./ap_startup_manual.md) for the full manual startup sequence (rfkill, hostapd, dnsmasq).
