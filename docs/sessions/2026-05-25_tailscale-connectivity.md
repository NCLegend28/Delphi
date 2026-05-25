# Session — Delphi Tailscale Connectivity Debug

**Date:** 2026-05-25
**Outcome:** Resolved. Service reachable at `https://delphi.tail6d29ca.ts.net/` once NordVPN is disconnected.

## TL;DR
"Tailscale isn't working" was **three separate things**, only the last of which was the real blocker — and **none were Tailscale itself**. We fixed a genuine Caddy/TLS deploy misconfiguration on the VM, ruled out the firewall and ACL, then traced the actual failure to **NordVPN** capturing Tailscale's WireGuard underlay on the Mac.

## Reported symptom
Couldn't reach the Delphi service over Tailscale; connection wouldn't go through.

## Topology
- VM `delphi` — Hetzner VPS, public IP `5.78.223.98`, tailnet `100.72.88.104`, tailnet `tail6d29ca`.
- Mac `talis-macbook-pro` — tailnet `100.70.97.66`.
- Edge: **Tailscale Serve terminates TLS** (`--https=443 → http://127.0.0.1:80`) → Caddy loopback `:80` → gateway `delphi:8080`.

## Findings (in order)

### 1. Network layer — healthy (ruled out)
- `tailscale ping delphi` → consistent ~70ms pong, direct path. Tunnel fine throughout.
- Early red herrings: ICMP `ping` to `100.x` timing out, TCP ports showing "closed" — explained, not bugs.

### 2. Caddy TLS misconfiguration — **fixed (real bug)**
- VM checks: all 4 containers healthy, `ufw` inactive, Tailscale Serve correctly configured.
- `https://delphi…/healthz` returned an **empty body**. `docker logs delphi-caddy-1` showed Caddy endlessly trying to get a Let's Encrypt cert for the placeholder **`delphi.example.com`** and issuing 308 HTTP→HTTPS redirects.
- **Root cause:** `.env.docker` had `DELPHI_DOMAIN=delphi.example.com`. Since Serve already terminates TLS, Caddy must serve plain HTTP.
- **Fix:**
  ```bash
  sed -i 's#^[[:space:]]*DELPHI_DOMAIN[[:space:]]*=.*#DELPHI_DOMAIN=:80#' .env.docker
  docker compose up -d --force-recreate caddy
  ```
- Verified locally: `curl -H "Host: delphi.tail6d29ca.ts.net" http://127.0.0.1:80/healthz` → `200 OK`, `{"status":"ok"}`, `Server: uvicorn`, `Via: 1.1 Caddy`.

### 3. Tailnet ACL — open (ruled out)
- `tailscale debug netmap` → `PacketFilter` `Srcs` included `100.64.0.0/11` (covers the Mac's `100.70.97.66`), all dsts/ports, TCP/UDP/ICMP. Policy genuinely allow-all.

### 4. NordVPN — **the actual blocker**
- VM-loopback `curl https://delphi.tail6d29ca.ts.net/healthz` → `{"status":"ok"}` ⇒ entire Delphi stack proven healthy.
- Mac TCP to `delphi:443` failed with `connect=0.000000s` (deterministic), even when forcing the tunnel IP via `--resolve`.
- `route get default` → gateway **`10.5.0.2` on `utun4`** = NordLynx (NordVPN WireGuard). `scutil --nwi` confirmed NordVPN was the default route; `NordVPN.app` + system extension running.
- **Mechanism:** NordVPN full-tunnel captured Tailscale's WireGuard underlay (WireGuard-in-WireGuard + kill-switch + MTU crush, `utun8` 1280 inside NordLynx 1420). Disco pings / DERP slipped through (so `tailscale ping` worked); sustained TCP never completed the handshake.
- **Fix:** disconnect / pause NordVPN. macOS NordVPN split-tunnel is app-based and does **not** reliably exclude Tailscale's system extension — don't rely on it.

## Bonus finding
Duplicate Tailscale install on the Mac: errored brew service (CLI v1.98.3) layered over the working GUI app extension (daemon v1.98.2) → the persistent version-mismatch warning. Recommended cleanup:
```bash
brew services stop tailscale && brew uninstall tailscale   # rely solely on the GUI app
```

## Changes made
- **VM:** `.env.docker` → `DELPHI_DOMAIN=:80`; recreated `delphi-caddy-1`. (File is gitignored — nothing to commit; confirm it persists across redeploys.)
- **Memory:** saved `delphi-connectivity.md` + `MEMORY.md` index.

## Reusable lesson
> `tailscale ping` works but TCP times out ⇒ **stop blaming Tailscale.** Walk the ladder: VM firewall → service listeners → proxy/Caddy logs → compiled ACL (`tailscale debug netmap`) → **then the client's local network** (here, a full-tunnel VPN). A node always reaches itself, so a VM-loopback `200` cleanly proves the fault is client-side.

## Remaining (optional)
- [ ] Decide NordVPN coexistence strategy (disconnect-when-needed is the reliable one).
- [ ] Clean up the duplicate brew Tailscale install on the Mac.
- [ ] Confirm `DELPHI_DOMAIN=:80` survives future redeploys / is documented in the deploy runbook.
