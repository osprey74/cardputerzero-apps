# CardputerZero Apps

> Application monorepo for the [M5Stack CardputerZero](https://shop.m5stack.com/pages/m5-cardputerzero) — a credit-card-sized Linux handheld powered by Raspberry Pi CM0.

[日本語版 README はこちら](./README.ja.md)

This repository hosts 15 planned applications for the CardputerZero — from a GPS logger with sky-plot visualization to a Meshtastic LoRa node, an NFC/Sub-GHz security toolkit, an off-grid BSAF disaster-alert receiver, an SDR wideband receiver, a LAN diagnostics tool and an offline star map.

> **Status (2026-11-19): 4 apps running on the device.** The GPS logger (App 01), Wi-Fi analyzer (App 07), LAN scanner (App 11) and star map (App 16) are implemented, packaged as `.deb`, and launched from the standard launcher on a real CardputerZero. The remaining apps are at the design or prototype stage; open items are tracked in [HANDOFF §9](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo). The apps are distributed locally and are not published to the official AppStore.

---

## Target Device

| Component | Specification |
|---|---|
| SoC | Broadcom BCM2837 / Quad-core Cortex-A53 @ 1GHz |
| RAM | 512MB LPDDR2 |
| LCD | 1.9" ST7789V2 (320×170) |
| Storage | microSD (32GB bundled with the standard edition) |
| Wireless | Wi-Fi 2.4GHz, Bluetooth 4.2/BLE |
| Wired | 10/100M Ethernet |
| USB | USB-C × 2 (Host/Slave switchable), USB-A × 1 |
| Camera | Sony IMX219 8MP (standard edition only) |
| OS | Raspberry Pi OS (Debian 13 trixie, Python 3.13 on the factory image) |
| Launcher | LVGL-based GUI launcher |
| AppStore | Debian `.deb` apt repository via [CardputerZeroRepository](https://github.com/m5stack/CardputerZeroRepository) |

Full hardware spec is in [HANDOFF §1](./HANDOFF_cardputerzero.md#1-ハードウェア概要).

### Cap Modules (interchangeable top slot)

| | Cap A: Cap LoRa-1262 | Cap B: Hacker Cap |
|---|---|---|
| Radio | SX1262 (LoRa, 868–923 MHz; transmission in Japan limited to 922.0–923.4 MHz) | CC1101 (Sub-GHz, 315/433/868/920 MHz; receive-only operation in Japan) |
| GNSS | AT6668 (GPS / QZSS / GLO / GAL / BDS) | — |
| NFC | — | ST25R3916 (ISO 14443A/B, FeliCa, ISO 15693) |
| Primary apps | App 01 / 02 / 05 | App 03 / 04 |

Cap A and Cap B share the same top-slot connector and cannot be mounted simultaneously. Caps are not hot-pluggable; power off before swapping. The GPS logger and the star map can also use an M5Stack Unit GPS v1.1 on the Grove port instead of the Cap's GNSS.

### Companion Hardware (recommended add-ons)

| Device | Role |
|---|---|
| [M5Stack C6L Meshtastic Unit](https://www.switch-science.com/products/10809) | Home-side LoRa gateway (Internet ↔ Meshtastic bridge, Wi-Fi 6 built-in) |
| [M5Stack Chain Encoder × 2](https://www.switch-science.com/collections/m5stack/products/10919) | Daisy-chained rotary knobs (frequency tuning / list scrolling) |
| [RTL-SDR Blog V4](https://www.rtl-sdr.com/rtl-sdr-blog-v4-dongle-initial-release/) | USB SDR dongle for 500 kHz – 1.75 GHz wideband reception |

---

## Applications

| ID | App | Priority | Hardware | Primary Function | Status |
|---|---|---|---|---|---|
| 01 | [`gps-logger`](./apps/gps-logger/) | ★★★★★ | Cap A or Grove GPS | GPX 1.1 track logger with speed/distance stats, sky plot of visible GNSS satellites and track view | **v0.1.0** |
| 02 | `lora-mesh-node` | ★★★★☆ | Cap A + C6L gateway | Meshtastic-compatible off-grid messaging node | Receive test tools only |
| 03 | `nfc-toolkit` | ★★★★☆ | Cap B | NFC card learning tool (ISO 14443A/B, FeliCa, ISO 15693) | Planned |
| 04 | `subghz-sniffer` | ★★★☆☆ | Cap B | Sub-GHz signal analyzer (receive-only in Japan) | Planned |
| 05 | `bsaf-client` | ★★★★☆ | Cap A + Wi-Fi | Two-channel ([BSAF v1](https://github.com/osprey74/bsaf-protocol)) disaster alert receiver (MQTT primary, LoRa fallback) | Planned |
| 06 | `edge-ai` | ★★★☆☆ | Built-in | Offline LLM assistant (quantized 1B-parameter models) | Planned |
| 07 | [`wifi-analyzer`](./apps/wifi-analyzer/) | ★★★☆☆ | Built-in | Nearby access-point list, 2.4 GHz channel map and signal graph (receive-only) | **v0.1.1** |
| 08 | `nfc-checkpoint` | ★★★☆☆ | Cap A + Cap B | NFC tag + GPS waypoint checkpoint logger | Planned |
| 09 | `nfc-lora-auth` | ★★☆☆☆ | Cap A + Cap B | Off-grid badge auth PoC (NFC scan → LoRa relay) | Planned |
| 10 | `sdr-receiver` | ★★★★☆ | RTL-SDR V4 | Wideband SDR receiver + integrated spectrum monitor (FM / ADS-B / AIS / NOAA APT / rtl_433) | Prototype (on uConsole) |
| 11 | [`lan-scanner`](./apps/lan-scanner/) | ★★★★☆ | Built-in | Host discovery (ICMP + ARP), mDNS/DNS names, vendor lookup and TCP port check on the connected subnet | **v0.1.1** |
| 13 | `tester` | ★★★★☆ | INA226 (Grove I2C) | DC voltage/current tester | Planned |
| 14 | `qr-toolkit` | ★★★★☆ | Built-in camera (standard edition) | QR code reader and structure analyzer | Planned |
| 15 | `ncir_thermometer` | ★★★☆☆ | MLX90614 + PaHUB (Grove) | Non-contact thermometer | Python PoC |
| 16 | [`stellar-map`](./apps/stellar-map/) | ★★★☆☆ | Built-in (GNSS optional) | Offline star map with planets and the Moon | **v0.1.6** |

App 12 was merged into App 10. Each app's full feature checklist is in [HANDOFF §3](./HANDOFF_cardputerzero.md#3-アプリ開発仕様).

---

## Tech Stack

- **Language**: The project policy prefers Rust, but the apps implemented so far are written in **Python**, because no aarch64 Linux Rust toolchain is set up yet. They depend only on what the factory image already provides (Python 3.13, Pillow, numpy), so nothing extra is installed with `apt`
- **UI**: Each app draws directly to the framebuffer (`/dev/fb0`, 320×170 RGB565) and reads the keyboard from evdev — the same way the standard launcher and its apps work. SDL2 windows do not appear on the LCD. The shared UI code is in [`shared/fb_ui`](./shared/fb_ui/) (Japanese text via Noto Sans CJK)
- **Runtime**: `legacy-deb-only` — each app is a standalone program registered with the launcher through `/usr/share/APPLaunch/applications/<name>.desktop`
- **Packaging**: [`scripts/pack_deb.sh`](./scripts/pack_deb.sh) builds a `.deb` from each app's `packaging/` directory. It needs `dpkg-deb`, so it is run on the device itself
- **Preview and testing**: Apps support `--headless` and `--script` (run without touching the LCD or keyboard and save PNG screenshots), and some support `--demo` (synthetic data), so screens can be checked on a PC or over SSH. The `czdev` emulator is not used
- **App Distribution**: Local only — `.deb` packages are installed with `apt install` on the developer's own device. They are not published to the official AppStore
- **Remote Development**: Tailscale VPN ↔ home Mac Mini for running full Claude models off-device (the 512MB RAM is too small for local LLM hosting)

---

## Repository Structure

```text
cardputerzero-apps/
├── CLAUDE.md
├── HANDOFF_cardputerzero.md     # Primary design specification
├── apps/                        # one directory per app: src/, packaging/, app-builder.json, README.md
│   ├── gps-logger/              # App 01  v0.1.0
│   ├── lora-mesh-node/          # App 02  receive test tools
│   ├── nfc-toolkit/             # App 03
│   ├── subghz-sniffer/          # App 04
│   ├── bsaf-client/             # App 05
│   ├── edge-ai/                 # App 06
│   ├── wifi-analyzer/           # App 07  v0.1.1
│   ├── nfc-checkpoint/          # App 08
│   ├── nfc-lora-auth/           # App 09
│   ├── sdr-receiver/            # App 10  prototype
│   ├── lan-scanner/             # App 11  v0.1.1
│   ├── tester/                  # App 13
│   ├── ncir_thermometer/        # App 15  Python PoC
│   └── stellar-map/             # App 16  v0.1.6
├── shared/
│   ├── fb_ui/                   # framebuffer UI + evdev keyboard (Python)
│   ├── gnss_at6668/             # GNSS driver: 5V power control for Cap/Grove, NMEA RMC/GGA/GSA/GSV
│   ├── star_catalog/            # star catalog and projection (App 16)
│   ├── compass/                 # heading (BMM150 etc.)
│   ├── cores3_bridge/           # USB CDC link to the CoreS3 front end
│   ├── lora_sx1262/             # SX1262 LoRa driver (planned)
│   ├── nfc_st25r3916/           # ST25R3916 NFC driver (planned)
│   ├── rf_cc1101/               # CC1101 Sub-GHz driver (planned)
│   ├── input_encoder/           # Chain Encoder input (planned)
│   └── ui_theme/                # shared theme (planned)
├── templates/                   # starter templates (rust-fb-app / rust-sdl2-app / python-sidecar-app)
├── firmware/                    # CoreS3 firmware (front end, level, timer)
├── scripts/                     # pack_deb.sh (.deb builder), deploy.sh, setup scripts
├── assets/                      # diagrams (SVG)
└── docs/                        # notes and certification documents
```

---

## Getting Started

### Preview an app on a PC

The UI code needs only Python 3 and Pillow + numpy. Apps with `--demo` run on a PC with synthetic data:

```bash
pip install pillow numpy
python apps/gps-logger/src/gps_logger.py --demo --headless \
  --script "4 enter; 30 shot /tmp/dash.png; 30.5 2; 31 shot /tmp/sky.png; 32 quit"
python -m unittest discover -s apps/gps-logger/tests
```

### Build and install on the device

```bash
# copy the repository (or the app, shared/ and scripts/) to the device, then on the device:
bash scripts/pack_deb.sh apps/gps-logger
apt-get -s install ./apps/gps-logger/dist-cz/*.deb    # dry run: check nothing else changes
sudo apt install ./apps/gps-logger/dist-cz/*.deb
```

The app then appears in the standard launcher. Long-press ESC to exit. On the keyboard, the cursor keys are Fn + F/X/C/Z; the apps also accept F/X/C/Z without Fn. See each app's README for its keys and options.

> Do not run `apt upgrade` on the device: the built-in Camera app depends on the exact libcamera version shipped in the factory image ([HANDOFF §9.1](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo)).

Device-side notes (first-boot wizard, SSH, launcher internals) are in [HANDOFF §4.2.1](./HANDOFF_cardputerzero.md) and [HANDOFF §6](./HANDOFF_cardputerzero.md#6-開発環境セットアップ).

---

## Japanese Regulatory Notes

All radio-frequency features ship with deliberate constraints for Japanese law compliance:

- **LoRa transmission**: limited to the conditions of the Cap LoRa-1262 Japanese certification (211-251216): eight channels in 922.0–923.4 MHz, 125 kHz bandwidth at 5 mW or less, each transmission under 0.4 s, carrier sense required, bundled antenna only. The device is operated receive-only until an implementation meeting these conditions is confirmed
- **Sub-GHz**: Cap CC1101 is operated receive-only. Its Japanese certification (219-269336) covers only 315 MHz and 922–923.4 MHz; 433 / 868 / 915 MHz must not be transmitted in Japan
- **NFC**: card emulation and UID writing restricted to user-owned cards for educational use
- **Wi-Fi analysis**: targets restricted to user-owned access points
- **LAN scanning**: only on networks where the operator has administrative authorization (per ISMS protocols)
- **SDR reception**: receive-only; rebroadcasting received content is prohibited under Radio Law §59

Details and citations are in [HANDOFF §7](./HANDOFF_cardputerzero.md#7-日本国内の法令技術基準).

---

## Ecosystem Integration

- **[Rindo](https://github.com/osprey74/Rindo-iOS)** — GPX exports from `gps-logger` (App 01) are designed to be imported into the Rindo cycling navigation app
- **[Michi-Navi](https://github.com/osprey74/michi-navi)** — `nfc-checkpoint` (App 08) is designed to integrate with the Hokkaido roadside-station stamp rally
- **[bsaf-protocol](https://github.com/osprey74/bsaf-protocol)** — `bsaf-client` (App 05) conforms to the BSAF v1 specification
- **bsaf-jma-bot** — App 05 subscribes to a BSAF MQTT feed when Wi-Fi is available, falling back to LoRa via the C6L gateway otherwise

---

## License

Released under the [MIT License](./LICENSE). Copyright © 2026 osprey74 (Sohshi).

---

## Links

- **Kickstarter**: https://www.kickstarter.com/projects/m5stack/cardputerzero
- **M5Stack Official Store**: https://shop.m5stack.com/pages/m5-cardputerzero
- **CardputerZero-AppBuilder**: https://github.com/m5stack/CardputerZero-AppBuilder
- **AppStore (apt repository)**: https://github.com/m5stack/CardputerZeroRepository
- **Cap LoRa-1262 (Cap A)**: https://docs.m5stack.com/ja/cap/Cap_LoRa-1262
- **Hacker Cap / Cap CC1101 (Cap B)**: https://docs.m5stack.com/en/cap/Cap_CC1101

---

## Author

**osprey74 (Sohshi)** — Bluesky: [@osprey74.bsky.social](https://bsky.app/profile/osprey74.bsky.social)
