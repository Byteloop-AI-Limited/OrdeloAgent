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

### 1b. Enable auto-login

So the Pi comes back up logged in after a reboot.

```bash
sudo raspi-config
```

Choose:

- **System Options**
  - **Auto Login**
    - enable **Console Auto Login**

Then reboot:

```bash
sudo reboot
```

---

## 2. Install git

```bash
sudo apt update
sudo apt install -y git curl wget
git --version
```

---

## 3. Install Go 1.23.2

The version in apt is too old for this repo.

```bash
cd /tmp
wget https://go.dev/dl/go1.23.2.linux-arm64.tar.gz
# 32-bit instead:
# wget https://go.dev/dl/go1.23.2.linux-armv6l.tar.gz

sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf go1.23.2.linux-arm64.tar.gz
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.profile
export PATH=$PATH:/usr/local/go/bin
go version
```

Must print `go1.23.2` or newer before continuing.

---

## 4. Clone the repo

```bash
cd ~
git clone https://YOUR_GITHUB_TOKEN@github.com/Byteloop-AI-Limited/receipt-service.git
cd receipt-service
git checkout fix/receipt-encoding-and-modifier-dedup
```

---

## 5. Build and install the binary

```bash
go build -o receipt-service ./pi
sudo install -m755 receipt-service /usr/local/bin/receipt-service
```

> Build `./pi` — **not** the repo root. The root `main.go` is an old version.

---

## 6. Run it as a service that starts on boot

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

## 7. Test the printer

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

## 8. Install cloudflared

```bash
cd /tmp
curl -L -o cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
# 32-bit instead:
# curl -L -o cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm.deb

sudo dpkg -i cloudflared.deb
cloudflared --version
```

---

## 9. Log in to Cloudflare

```bash
cloudflared tunnel login
```

Opens the browser on the Pi. If it doesn't, it prints a URL — paste that into
Chromium on the Pi. Log in and select the `byteloop.ai` zone. Writes
`~/.cloudflared/cert.pem`.

---

## 10. Create the tunnel

```bash
cloudflared tunnel create bnat-print
cloudflared tunnel list
```

**Write down the UUID it prints** — needed in step 12.

---

## 11. Create the DNS record

```bash
cloudflared tunnel route dns bnat-print bnat-print.byteloop.ai
dig +short bnat-print.byteloop.ai
```

Creates the proxied CNAME in Cloudflare automatically — no dashboard needed.

---

## 12. Tunnel config

```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/*.json /etc/cloudflared/
sudo nano /etc/cloudflared/config.yml
```

Paste this, replacing **both** occurrences of `PASTE-UUID-HERE` with the UUID
from step 10:

```yaml
tunnel: PASTE-UUID-HERE
credentials-file: /etc/cloudflared/PASTE-UUID-HERE.json

ingress:
  - hostname: bnat-print.byteloop.ai
    service: http://localhost:8080
  - service: http_status:404
```

As filled in for this deployment:

```yaml
tunnel: d8f8c7d0-865d-47b4-a14a-d9287314bd3b
credentials-file: /etc/cloudflared/d8f8c7d0-865d-47b4-a14a-d9287314bd3b.json

ingress:
  - hostname: bnat-print.byteloop.ai
    service: http://localhost:8080
  - service: http_status:404
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`. Then validate:

```bash
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
```

---

## 13. Make the tunnel start on boot

```bash
sudo cloudflared --config /etc/cloudflared/config.yml service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared --no-pager
```

Look for `Registered tunnel connection` in the output — usually four, one per
Cloudflare edge datacentre.

---

## 14. Test through the public hostname

Still on the Pi:

```bash
curl https://bnat-print.byteloop.ai/healthz
```

```bash
curl -i -X POST https://bnat-print.byteloop.ai/ \
  -H 'Content-Type: application/json' \
  -H 'X-Authorization: Bearer jUo7Wsc****' \
  -d '{"order_id":"TUNNEL-001","restaurant":"Burger Nation","status":"collection",
       "total":"8.99","items":[{"name":"Chicken Popcorn","price":"8.99","quantity":1}]}'
```

This goes out to Cloudflare and back down the tunnel. Paper means the whole
chain works.

---

## 15. Reboot test

```bash
sudo reboot
```

When it comes back:

```bash
systemctl is-enabled receipt-service cloudflared
systemctl is-active  receipt-service cloudflared
curl https://bnat-print.byteloop.ai/healthz
```

All four must read `enabled` / `active`, and the health check must return `ok`.
If anything reads `disabled`, run `sudo systemctl enable <name>` and reboot
again.

---

## 16. Point payment-service at it

In the payment-service repo, [config.go:213](payment-service/internal/config/config.go#L213):

```go
PrintURL: "https://bnat-print.byteloop.ai",
```

Same value in [config.yaml:39](payment-service/internal/config/config.yaml#L39),
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

## Remote SSH through the tunnel

SSH shares the existing `bnat-print` tunnel — no new tunnel, no port
forwarding. The receipt service on 8080 is untouched; this only adds a second
ingress rule.

### On the Pi — tunnel config

Edit `/etc/cloudflared/config.yml` and add the SSH rule **before** the
catch-all 404:

```yaml
tunnel: d8f8c7d0-865d-47b4-a14a-d9287314bd3b
credentials-file: /etc/cloudflared/d8f8c7d0-865d-47b4-a14a-d9287314bd3b.json

ingress:
  - hostname: bnat-print-ssh.byteloop.ai
    service: ssh://localhost:22
  - hostname: bnat-print.byteloop.ai
    service: http://localhost:8080
  - service: http_status:404
```

### On the Pi — DNS route + restart

`route dns` is per-hostname: this adds a second CNAME for `bnat-print-ssh.byteloop.ai`
pointing at the same tunnel, leaving the existing record alone.

```bash
cloudflared tunnel route dns bnat-print bnat-print-ssh.byteloop.ai
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
sudo systemctl restart cloudflared
```

Make sure sshd is up (usually is on Pi OS):

```bash
sudo systemctl enable --now ssh
sudo ss -lntp | grep :22
```

### On the remote machine (your Mac)

Raw `ssh` cannot cross Cloudflare on its own — the client needs `cloudflared`
to proxy the connection.

```bash
brew install cloudflared
```

Append to `~/.ssh/config` **on the Mac** (not the Pi):

```bash
cat >> ~/.ssh/config <<'EOF'

Host bnat-print-ssh.byteloop.ai
  ProxyCommand cloudflared access ssh --hostname %h
EOF
```

`%h` is a literal ssh token that expands to the hostname — paste it as-is.
No restart needed; the file is read on every ssh invocation. Then connect
with the Pi's username:

```bash
ssh byteloop@bnat-print-ssh.byteloop.ai
```

Accept the host key prompt, then enter the `byteloop` user's password.

### Debugging

| Symptom | Likely cause |
|---|---|
| `port 22: Operation timed out` | ProxyCommand not applied — config went on the Pi instead of the Mac, or cloudflared isn't installed on the Mac |
| `404` / hostname errors in `journalctl -u cloudflared` | SSH ingress rule missing from config.yml |
| `dig +short bnat-print-ssh.byteloop.ai` returns nothing | DNS route didn't take — re-run `route dns` |

Checks, in order:

```bash
# Mac — is the config block being picked up?
ssh -G bnat-print-ssh.byteloop.ai | grep -i proxycommand

# Mac — raw tunnel test; an SSH-2.0-OpenSSH banner means the chain works
cloudflared access ssh --hostname bnat-print-ssh.byteloop.ai

# Pi — tunnel logs after restart
journalctl -u cloudflared -n 50 --no-pager
```

### Security

Exposing SSH via the tunnel makes sshd reachable from the whole internet —
password auth still applies, but bots will find it. Switch to key-only auth:

```bash
# Mac — create a key if you don't have one, then install it on the Pi
ssh-keygen -t ed25519
ssh-copy-id byteloop@bnat-print-ssh.byteloop.ai

# verify `ssh byteloop@bnat-print-ssh.byteloop.ai` logs in WITHOUT a password first,
# then on the Pi:
sudo tee /etc/ssh/sshd_config.d/99-key-only.conf <<'EOF'
PasswordAuthentication no
PubkeyAuthentication yes
EOF
sudo systemctl restart ssh
```

Keep the current session open until a fresh key-based login works, so you
don't lock yourself out. SSH keys have no relation to the HTTP bearer token —
the 8080 service keeps its token auth, SSH uses keys.

