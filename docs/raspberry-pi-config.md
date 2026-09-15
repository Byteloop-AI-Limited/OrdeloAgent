# Receipt Service — Raspberry Pi Setup

Deploy the receipt service on a Raspberry Pi with a USB thermal printer, expose
it through a Cloudflare tunnel, and have both survive a reboot.

Every command below runs **on the Pi itself**.

---

## 1. Check the architecture

```bash
uname -m
```

| Output | Use |
|---|---|
| `aarch64` | the **arm64** downloads below |
| `armv7l` / `armv6l` | the **armv6l / arm** downloads below |

### 1.1 Enable auto-login

This Pi is unattended. Its attached console must always start a shell as the
`byteloop` user after boot; it must not stop at a `login:` prompt. The receipt
service, `cloudflared`, and SSH are system services and start independently of
this login, but console auto-login makes local recovery possible without a
keyboard/password exchange.

> **Do not rely on Raspberry Pi Imager's username/password fields as the
> acceptance check for this.** They provision the account (and can enable SSH),
> but the selected OS image and its first-boot customisation determine whether
> console auto-login is actually enabled. Always apply and verify the setting
> below after the first boot of a newly imaged card.

Run this while signed in as `byteloop` (not `root`). It selects **B2**, the
Raspberry Pi OS console-auto-login boot mode, for the account that invoked
`sudo`:

```bash
test "$(id -un)" = "byteloop" || { echo "Sign in as byteloop first"; exit 1; }
sudo raspi-config nonint do_boot_behaviour B2
if systemctl cat autologin@tty1.service >/dev/null 2>&1; then
  sudo systemctl cat autologin@tty1.service
else
  sudo cat /etc/systemd/system/getty@tty1.service.d/autologin.conf
fi
```

In the displayed unit or override, the `agetty` command must include
`--autologin byteloop`. Raspberry Pi OS Bookworm and older releases use the
`getty@tty1.service.d/autologin.conf` override; newer releases can use the
standalone `autologin@tty1.service` unit. Therefore,
`systemctl is-enabled autologin@tty1.service` returning `not-found` is normal
on the former and is not a failure.

Automatic console login deliberately does **not** put the account password in
a script or type it at boot: it logs the configured local console account in
without asking for it. The existing account password remains the password for
SSH unless SSH is later changed to key-only authentication.

If you prefer the menu, it configures the same setting:

```bash
sudo raspi-config
```

Choose:

- **System Options**
  - **Auto Login**
    - enable **Console Auto Login**

Reboot and confirm from the attached display that the prompt is already
`byteloop@...` rather than `login:`:

```bash
sudo reboot
```

> Do not hand-edit a getty override from instructions for another Raspberry Pi
> OS release. Use `raspi-config` and inspect its result using the version-aware
> check above.

### 1.2 Connect to Wi-Fi

Raspberry Pi OS (Bullseye and later) uses NetworkManager, so `nmcli` works
purely from the terminal — no desktop needed.

Check you're on NetworkManager:

```bash
nmcli --version
```

List visible networks:

```bash
sudo nmcli device wifi list
nmcli connection show
```

Connect:

```bash
sudo nmcli device wifi connect "XLN_Small_Biz_J5s3" password "YOUR_PASSWORD"
```

Verify:

```bash
nmcli device status
ip a show wlan0
ping -c 3 8.8.8.8
```

`nmcli device status` should show `wlan0` as `connected`. The connection
persists across reboots automatically — no extra step needed.

> **Older Raspberry Pi OS (pre-Bullseye, `dhcpcd`-based) instead:**
> ```bash
> sudo raspi-config nonint do_wifi_ssid_passphrase "YOUR_SSID" "YOUR_PASSWORD"
> sudo systemctl restart dhcpcd
> ```
> Or edit `/etc/wpa_supplicant/wpa_supplicant.conf` directly and add:
> ```
> network={
>     ssid="YOUR_SSID"
>     psk="YOUR_PASSWORD"
> }
> ```
> then `sudo wpa_cli -i wlan0 reconfigure`.

#### 1.2.1 Pre-configure a network that isn't in range yet

`nmcli device wifi connect` only works against networks currently visible in
a scan — if the SSID isn't broadcasting yet, it fails with `No network with
SSID found` and **nothing is saved**. To save the profile ahead of time,
create it directly instead of scanning for it:

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name "YOUR_SSID" ssid "YOUR_SSID"
sudo nmcli connection modify "YOUR_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "YOUR_PASSWORD"
```

For this deployment, run these for both networks:

```bash
# byteloop
sudo nmcli connection add type wifi ifname wlan0 con-name "byteloop" ssid "byteloop"
sudo nmcli connection modify "byteloop" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "byteloop123"

# XLN_Small_Biz_J5s3
sudo nmcli connection add type wifi ifname wlan0 con-name "XLN_Small_Biz_J5s3" ssid "XLN_Small_Biz_J5s3"
sudo nmcli connection modify "XLN_Small_Biz_J5s3" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "c5Rgfyu7"
```

Confirm it saved:

```bash
nmcli connection show
```

It'll appear in the list even though it's not active yet. `autoconnect` is
`yes` by default, so once that SSID comes into range the Pi joins it
automatically — no need to run `connection up` yourself.

If the network is hidden (doesn't broadcast its SSID at all, as opposed to
just being off right now), also add:

```bash
sudo nmcli connection modify "YOUR_SSID" 802-11-wireless.hidden yes
```

#### 1.2.2 Switch between already-connected Wi-Fi networks

`nmcli` saves a connection profile for every network you've ever connected
to, so switching back doesn't need the password again.

List saved profiles:

```bash
nmcli connection show
```

Check which one is currently active:

```bash
nmcli -t -f active,ssid dev wifi | grep '^yes'
```

Switch to a saved network by name:

```bash
sudo nmcli connection up "OTHER_SSID"
```

This brings down the current Wi-Fi connection and brings the named one up —
no need to disconnect manually first.

To forget a saved network entirely (deletes the stored password too):

```bash
sudo nmcli connection delete "OLD_SSID"
```

#### P.S. Optional Wi-Fi details

##### Password contains `!`

If the password contains `!`, bash may try to expand it as a history event,
even inside quotes, and fail with `bash: !...: event not found`. Read the
password into a variable instead:

```bash
read -s -p "Wi-Fi password: " WIFI_PASS; echo
sudo nmcli device wifi connect "YOUR_SSID" password "$WIFI_PASS"
unset WIFI_PASS
```

This also keeps the password out of shell history. Alternatively, disable
history expansion for the session with `set +H` before using the main command.

##### Prefer `netplan-wlan0-10hith`, then fall back to `BT-M9CW3Q`

Set these on the saved **connection profiles**. They only change the next
automatic connection decision; they do not interrupt the current Wi-Fi or SSH
session.

```bash
# Higher priority for byteloop
sudo nmcli connection modify "byteloop" \
  connection.autoconnect yes \
  connection.autoconnect-priority 100 \
  connection.autoconnect-retries 1

sudo nmcli connection modify "BT-M9CW3Q" \
  connection.autoconnect yes \
  connection.autoconnect-priority 50
```

At boot, or whenever `wlan0` is disconnected, NetworkManager chooses the
available candidate with the higher priority. It will try the preferred
`netplan-wlan0-10hith` profile once; if that activation fails, it can select
`BT-M9CW3Q` rather than making the default multiple attempts first. The
numbers are arbitrary — only `100 > 50` matters.

Verify the saved settings without reconnecting:

```bash
nmcli -f NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY,AUTOCONNECT-RETRIES connection show
```

> A priority does not pre-empt a healthy active connection. If the Pi is
> already connected to BT and `netplan-wlan0-10hith` later appears, it stays
> on BT until the connection drops or the Pi reboots. An automatic live
> switch-back would need a separate NetworkManager dispatcher policy.

##### Test the priority and fallback

Perform this test from the Pi's attached console, not from the only SSH
session: each reboot intentionally interrupts remote access.

First, with **both** SSIDs available, confirm that NetworkManager can see
them, then reboot:

```bash
# Rescan to pick up any new networks
sudo nmcli device wifi list --rescan yes 
# Show which one is currently active
nmcli -f IN-USE,SSID,SIGNAL device wifi list --rescan yes
sudo reboot
```

After it returns, this must show `yes:netplan-wlan0-10hith`:

```bash
nmcli -t -f active,ssid device wifi | grep '^yes:'
```

Next, make `netplan-wlan0-10hith` genuinely unavailable (turn off its access
point or move the Pi out of its range) while leaving `BT-M9CW3Q` available,
then reboot again. The same check must show `yes:BT-M9CW3Q`. Restore the
preferred access point and reboot one final time; it must return to
`netplan-wlan0-10hith`.

`connection.autoconnect-retries 1` limits the preferred profile to one
activation attempt, but does not promise an exact number of seconds: Wi-Fi
association and DHCP timing depend on the access point and signal.

---

## 2. Install all dependencies

```bash
sudo apt update && sudo apt install -y git curl wget golang nodejs npm
```

> The `golang` package in apt can lag behind what the repo needs. If
> `go build` later complains about the Go version, install Go 1.23.2
> manually from https://go.dev/dl/ (linux-arm64 tarball) and prepend
> `/usr/local/go/bin` to your `PATH`.

---

## 3. Clone the repo

```bash
cd ~
git clone https://github.com/Byteloop-AI-Limited/receipt-service.git
cd receipt-service
git checkout fix/receipt-encoding-and-modifier-dedup
```

---

## 4. Build and install the binary

```bash
go build -o receipt-service ./pi
sudo install -m755 receipt-service /usr/local/bin/receipt-service
```

> Build `./pi` — **not** the repo root. The root `main.go` is an old version.

---

## 5. Run it as a service that starts on boot

```bash
sudo tee /etc/systemd/system/receipt-service.service >/dev/null <<'EOF'
[Unit]
Description=Byteloop receipt service
After=network-online.target
Wants=network-online.target

[Service]
User=byteloop
ExecStart=/usr/local/bin/receipt-service
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now receipt-service
sudo systemctl status receipt-service --no-pager
```

Expect `Active: active (running)` and `Loaded: ... enabled`.

---

## 6. Test the printer

Health check:

```bash
curl http://localhost:8080/healthz
```

Test print:

```bash
curl -i -X POST http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -H 'X-Authorization: Bearer jUo7W****' \
  -d '{"order_id":"TEST-001","restaurant":"Burger Nation","status":"collection",
       "total":"8.99","items":[{"name":"Chicken Popcorn","price":"8.99","quantity":1}]}'
```

**A receipt must come out of the printer before you continue.**

| Response | Meaning |
|---|---|
| `200` | Printed |
| `401 Unauthorized` | Token mismatch — must include the `Bearer ` prefix |
| `503 Printer is offline` | `/dev/usb/lp0` not found |
| `500 failed writing to printer` | Device present, write failed |

---

## 7. Install cloudflared

```bash
cd /tmp
curl -L -o cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
# 32-bit instead:
# curl -L -o cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm.deb

sudo dpkg -i cloudflared.deb
cloudflared --version
```

---

### 7.1 Log in to Cloudflare

```bash
cloudflared tunnel login
```

Opens the browser on the Pi. If it doesn't, it prints a URL — paste that into
Chromium on the Pi. Log in and select the `byteloop.ai` zone. Writes
`~/.cloudflared/cert.pem`.

### 7.2 Create the tunnel

```bash
cloudflared tunnel create bnat-print
cloudflared tunnel list
```

**Write down the UUID it prints** — needed in section 7.4.

> **Tunnel already exists from an old Pi that's gone?** A tunnel belongs to
> its credentials file (`~/.cloudflared/<UUID>.json`), not the hardware —
> `tunnel create bnat-print` here will fail with a name conflict. Either:
>
> - **Reuse it:** in the Cloudflare Zero Trust dashboard → Networks →
>   Tunnels → `bnat-print` → Configure, copy the install token and run
>   `sudo cloudflared service install <TOKEN>` on the new Pi. The UUID and
>   DNS records stay as-is; your local `config.yml` ingress rules still apply.
> - **Start clean:** `cloudflared tunnel delete bnat-print` (after
>   `tunnel login`), then `tunnel create` again — this prints a **new UUID**,
>   so re-run `route dns` (section 7.3) and update both UUIDs in `config.yml`
>   (section 7.4). The old CNAME points at the dead tunnel until you re-run
>   `route dns`.

### 7.3 Create the DNS records

```bash
cloudflared tunnel route dns bnat-print bnat-print.byteloop.ai
cloudflared tunnel route dns bnat-print bnat-print-ssh.byteloop.ai
dig +short bnat-print.byteloop.ai
dig +short bnat-print-ssh.byteloop.ai
```

Creates proxied CNAMEs for both hostnames automatically — no dashboard needed.
`bnat-print-ssh.byteloop.ai` uses the same tunnel as the print service.

#### 7.3.1 Inspect or remove an existing DNS record

If `route dns` reports code `1003`, the hostname already has an A, AAAA, or
CNAME record. In the Cloudflare dashboard, open **DNS → Records** for
`byteloop.ai`, search for the hostname, and delete the confirmed stale record.

Alternatively, keep the hostname and repoint it to the current tunnel without
deleting it:

```bash
cloudflared tunnel route dns --overwrite-dns bnat-print bnat-print.byteloop.ai
cloudflared tunnel route dns --overwrite-dns bnat-print bnat-print-ssh.byteloop.ai
```

### 7.4 Configure the tunnel

```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/*.json /etc/cloudflared/
sudo nano /etc/cloudflared/config.yml
```

Paste this, replacing **both** occurrences of `PASTE-UUID-HERE` with the UUID
from section 7.2:

```yaml
tunnel: PASTE-UUID-HERE
credentials-file: /etc/cloudflared/PASTE-UUID-HERE.json

ingress:
  # Remote SSH to the Pi
  - hostname: bnat-print-ssh.byteloop.ai
    service: ssh://localhost:22
  # Receipt-printing service
  - hostname: bnat-print.byteloop.ai
    service: http://localhost:8080
  - service: http_status:404
```

As filled in for this deployment:

```yaml
tunnel: d8f8c7d0-865d-47b4-a14a-d9287314bd3b
credentials-file: /etc/cloudflared/d8f8c7d0-865d-47b4-a14a-d9287314bd3b.json

ingress:
  # Remote SSH to the Pi
  - hostname: bnat-print-ssh.byteloop.ai
    service: ssh://localhost:22
  # Receipt-printing service
  - hostname: bnat-print.byteloop.ai
    service: http://localhost:8080
  - service: http_status:404
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`. Then validate:

```bash
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
```

### 7.5 Start the tunnel and enable it on boot

```bash
sudo cloudflared --config /etc/cloudflared/config.yml service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared --no-pager
```

Look for `Registered tunnel connection` in the output — usually four, one per
Cloudflare edge datacentre.

### 7.6 Configure SSH access

Enable the Pi's SSH service:

```bash
sudo systemctl enable --now ssh
```

On the remote Mac, install `cloudflared`, then add this host entry to
`~/.ssh/config`:

```bash
brew install cloudflared
nano ~/.ssh/config
```

```sshconfig
Host bnat-print-ssh.byteloop.ai
  ProxyCommand cloudflared access ssh --hostname %h
```

Connect with the Pi username:

```bash
ssh byteloop@bnat-print-ssh.byteloop.ai
```

Use an SSH key and a Cloudflare Access policy before relying on remote access.

---

## 8. Test through the public hostname

Still on the Pi:

```bash
curl https://bnat-print.byteloop.ai/healthz
```

```bash
curl -i -X POST https://bnat-print.byteloop.ai/ \
  -H 'Content-Type: application/json' \
  -H 'X-Authorization: Bearer jUo7WsyYySxi71GwieuFPBfbWj8xR6DaXjUHW7gccT1EaX0DCCm3R3qTmJ3FWh2cFRI7jKOCBodFAvp' \
  -d '{"order_id":"TUNNEL-001","restaurant":"arna is the best","status":"collection",
       "total":"8.99","items":[{"name":"Chicken Popcorn","price":"8.99","quantity":1}]}'
```

This goes out to Cloudflare and back down the tunnel. Paper means the whole
chain works.

---

## 9. Reboot test

```bash
sudo reboot
```

When it comes back:

```bash
systemctl is-enabled receipt-service cloudflared ssh
systemctl is-active  receipt-service cloudflared ssh
curl https://bnat-print.byteloop.ai/healthz
```

The first six results must read `enabled` / `active`, and the health check
must return `ok`. The attached console must already be logged in as
`byteloop`, with no `login:` prompt. If a service reads `disabled`, run
`sudo systemctl enable <name>` and reboot again. If the console asks for a
login, repeat section 1.1 while signed in as `byteloop` and re-check that
the displayed `agetty` command contains `--autologin byteloop` before
rebooting.

---

## 10. Point payment-service at it

In the payment-service repo, `internal/config/config.go` (around line 213):

```go
PrintURL: "https://bnat-print.byteloop.ai",
```

Same value in `internal/config/config.yaml` (around line 39),
then redeploy the Lambda.

> `config.go` is what takes effect in production. `config.yaml` is only read
> when AWS Secrets Manager is unreachable — changing the YAML alone does
> nothing in prod.

---

## Deploying a newer build later

```bash
cd ~/receipt-service
git pull
go build -o receipt-service ./pi
sudo install -m755 receipt-service /usr/local/bin/receipt-service
sudo systemctl restart receipt-service
```

---

## Troubleshooting

| What | Command |
|---|---|
| Receipt service logs | `journalctl -u receipt-service -f` |
| Tunnel logs | `journalctl -u cloudflared -f` |
| Is port 8080 listening | `sudo ss -lntp \| grep 8080` |
| Printer device present | `ls -l /dev/usb/lp0` |
| Restart the service | `sudo systemctl restart receipt-service` |
| Restart the tunnel | `sudo systemctl restart cloudflared` |
| Tunnel state at Cloudflare | `cloudflared tunnel info bnat-print` |

---

## Notes

- The service token is compiled into the binary and must match `token` in
  `prod/elai/secrets`, which is what payment-service sends. Override it without
  rebuilding by adding
  `Environment=RECEIPT_SERVICE_TOKEN=Bearer <token>` to the systemd unit — the
  value must include the literal `Bearer ` prefix.
- Override the device path the same way with `Environment=PRINTER_DEVICE=/dev/usb/lp1`.
- The service binds `0.0.0.0:8080`, so it is reachable from the LAN as well as
  through the tunnel. cloudflared connects over localhost, so make sure the
  router does **not** port-forward 8080.

---
