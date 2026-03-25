# Tailscale VPN

Installed directly on Fedora host (not in k3s).

## Server setup
sudo tailscale up --advertise-routes=192.168.87.0/24

## Tailscale IP
100.72.229.55

## DNS
AdGuard set as global nameserver in Tailscale admin console
https://login.tailscale.com/admin/dns

## Client setup
sudo tailscale up --accept-routes
