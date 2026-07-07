# Instruction: Reolink Camera Operation

**Version:** 1.0.0
**Created:** 2026-05-21
**Last Updated:** 2026-05-21
**Status:** active
**Priority:** medium
**Applies To:** AI instances with camera access

## Hardware

**Model:** Reolink E1 Zoom (4K variant)
**Quantity:** 2 units
**Cost:** ~$100 each

| Spec | Value |
|---|---|
| Resolution | 3840 x 2160 (4K) |
| PTZ | 355° pan, 50° tilt, 5x optical zoom |
| Connectivity | WiFi 2.4/5 GHz + Ethernet |
| API Ports | HTTP (80), RTSP (554), Reolink proprietary (9000) |
| Power | USB-C, 5V/2A |
| Night Vision | IR LEDs, auto day/night switching |
| Audio | Two-way (not used) |

**Identifiers:**
- **AI-Lens-L:** Left/west camera (white unit)
- **AI-Lens-R:** Right/east camera (black unit)

## Network

Both cameras connect via WiFi to the local LAN. DHCP reservations are configured on the ASUS RT-AX5400 router for stable IPs.

**Credentials:** Stored in `$AI_ROOT/.credentials/reolink.env` (gitignored). Source this file before any camera operations:
```bash
source $AI_ROOT/.credentials/reolink.env
# Provides: REOLINK_USER, REOLINK_PASS, REOLINK_HOST_L, REOLINK_HOST_R
```

**Important:** Camera IPs may change if the Mac or cameras switch WiFi networks. If a camera is unreachable:
1. Ping the expected IP
2. If unreachable, sweep the subnet: `for i in $(seq 1 254); do ping -c 1 -t 1 192.168.50.$i >/dev/null 2>&1 & done; wait; arp -a | grep -v incomplete`
3. Try Reolink login on discovered IPs to identify cameras
4. Update `.credentials/reolink.env` with the correct IP

**Port troubleshooting:** After network changes, cameras may have HTTP/RTSP ports closed despite settings showing them enabled. Fix: reboot the camera from the Reolink phone app (Settings > System > Reboot).

## Authentication

Tokens are valid for 1 hour (3600 seconds). Re-authenticate when tokens expire.

```bash
TOKEN=$(curl -s --connect-timeout 5 "http://$HOST/api.cgi?cmd=Login" \
  -d "[{\"cmd\":\"Login\",\"param\":{\"User\":{\"userName\":\"$REOLINK_USER\",\"password\":\"$REOLINK_PASS\"}}}]" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['value']['Token']['name'])")
```

**Response format:** All API responses are JSON arrays. Success = `"code": 0`. Errors include `"code": 1` with an `"error"` object.

## Capturing Snapshots

```bash
curl -s "http://$HOST/cgi-bin/api.cgi?cmd=Snap&channel=0&token=$TOKEN" -o /tmp/snapshot.jpg
```

Note the different path: `/cgi-bin/api.cgi` for snapshots vs `/api.cgi` for all other commands.

Output is a JPEG at the camera's current resolution (3840x2160 at default).

## PTZ Control

### Movement Commands

Pan, tilt, and zoom use timed speed commands. The camera moves continuously until stopped.

```bash
# Start moving (op: Left, Right, Up, Down, ZoomInc, ZoomDec)
curl -s "http://$HOST/api.cgi?cmd=PtzCtrl&token=$TOKEN" \
  -d '[{"cmd":"PtzCtrl","param":{"channel":0,"op":"Right","speed":20}}]'

# MUST stop explicitly
curl -s "http://$HOST/api.cgi?cmd=PtzCtrl&token=$TOKEN" \
  -d '[{"cmd":"PtzCtrl","param":{"channel":0,"op":"Stop"}}]'
```

**Speed range:** 1-60. Lower = slower/more precise, higher = faster. Recommend 8-15 for fine adjustments, 20-30 for large movements.

**Critical limitation:** There are no absolute position commands. PTZ is relative only. Timed speed commands overshoot consistently. **Always use presets to return to known positions** rather than trying to reverse movements.

### Presets

Save and recall named positions. This is the only reliable positioning method.

```bash
# Save current position as preset
curl -s "http://$HOST/api.cgi?cmd=SetPtzPreset&token=$TOKEN" \
  -d '[{"cmd":"SetPtzPreset","param":{"PtzPreset":{"channel":0,"enable":1,"id":0,"name":"board_home"}}}]'

# Go to preset
curl -s "http://$HOST/api.cgi?cmd=PtzCtrl&token=$TOKEN" \
  -d '[{"cmd":"PtzCtrl","param":{"channel":0,"op":"ToPos","speed":32,"id":0}}]'
```

**Current presets:**
- id:0 "board_home" — default board overview position (both cameras)

### Zoom/Focus Readback

```bash
curl -s "http://$HOST/api.cgi?cmd=GetZoomFocus&token=$TOKEN" \
  -d '[{"cmd":"GetZoomFocus","param":{"channel":0}}]'
```

Returns `zoom.pos` and `focus.pos` values. No absolute pan/tilt readback is available.

### AutoFocus

The `AutoFocus` PTZ op is not supported on this model. Focus adjusts automatically with zoom changes.

## Image Settings (ISP)

The AI can tune image processing to improve visibility. Current optimized settings for board game use:

```bash
# Image adjustments (bright, contrast, hue, saturation, sharpen: range 0-255)
curl -s "http://$HOST/api.cgi?cmd=SetImage&token=$TOKEN" \
  -d '[{"cmd":"SetImage","param":{"Image":{
    "channel":0,"bright":128,"contrast":160,
    "hue":128,"saturation":180,"sharpen":160}}}]'

# ISP adjustments (backlight compensation, dynamic range)
curl -s "http://$HOST/api.cgi?cmd=SetIsp&token=$TOKEN" \
  -d '[{"cmd":"SetIsp","param":{"Isp":{
    "channel":0,"backLight":"DynamicRangeControl","drc":200}}}]'
```

| Setting | Default | Optimized | Purpose |
|---|---|---|---|
| Backlight | Off | DynamicRangeControl | Compensates for glare from overhead lighting |
| DRC | 128 | 200 | Balances bright/dark regions in frame |
| Saturation | 128 | 180 | Separates similar piece colors (green/beige/brown) |
| Contrast | 128 | 160 | Sharpens piece edges against board artwork |
| Sharpen | 128 | 160 | Improves fine detail at distance |

## Device Information

```bash
# Device name
curl -s "http://$HOST/api.cgi?cmd=GetDevName&token=$TOKEN" \
  -d '[{"cmd":"GetDevName","param":{"channel":0}}]'

# Full device info (model, firmware, serial)
curl -s "http://$HOST/api.cgi?cmd=GetDevInfo&token=$TOKEN" \
  -d '[{"cmd":"GetDevInfo","param":{}}]'

# Current ISP settings
curl -s "http://$HOST/api.cgi?cmd=GetIsp&token=$TOKEN" \
  -d '[{"cmd":"GetIsp","param":{"channel":0}}]'

# Current image settings
curl -s "http://$HOST/api.cgi?cmd=GetImage&token=$TOKEN" \
  -d '[{"cmd":"GetImage","param":{"channel":0}}]'
```

## Operational Patterns

### Standard survey sequence
```bash
source $AI_ROOT/.credentials/reolink.env

# Login both cameras
TOKEN_L=$(curl -s "http://$REOLINK_HOST_L/api.cgi?cmd=Login" ...)
TOKEN_R=$(curl -s "http://$REOLINK_HOST_R/api.cgi?cmd=Login" ...)

# Return to home presets
curl -s "http://$REOLINK_HOST_L/api.cgi?cmd=PtzCtrl&token=$TOKEN_L" \
  -d '[{"cmd":"PtzCtrl","param":{"channel":0,"op":"ToPos","speed":32,"id":0}}]'
curl -s "http://$REOLINK_HOST_R/api.cgi?cmd=PtzCtrl&token=$TOKEN_R" \
  -d '[{"cmd":"PtzCtrl","param":{"channel":0,"op":"ToPos","speed":32,"id":0}}]'

sleep 3  # wait for PTZ to settle

# Snap both
curl -s "http://$REOLINK_HOST_L/cgi-bin/api.cgi?cmd=Snap&channel=0&token=$TOKEN_L" -o /tmp/survey_l.jpg
curl -s "http://$REOLINK_HOST_R/cgi-bin/api.cgi?cmd=Snap&channel=0&token=$TOKEN_R" -o /tmp/survey_r.jpg
```

### Key gotchas
- **Snapshot endpoint differs:** `/cgi-bin/api.cgi` not `/api.cgi`
- **Stop is required after movement.** Omitting Stop leaves the camera panning indefinitely.
- **Tokens expire silently.** A `"please login first"` error means re-authenticate.
- **Camera may be on wrong IP.** Always verify connectivity before assuming a camera is down.
- **Images have no persistent memory.** Observations from snapshots must be written to text/files immediately or they are lost on the next conversation turn.
