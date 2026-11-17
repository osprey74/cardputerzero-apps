# CardputerZero Apps

> Application monorepo for the [M5Stack CardputerZero](https://shop.m5stack.com/pages/m5-cardputerzero) — a credit-card-sized Linux handheld powered by Raspberry Pi CM0.

[日本語版 README はこちら](./README.ja.md)

This repository hosts 11 planned applications for the CardputerZero — from a GPS logger with sky-plot visualization to a Meshtastic LoRa node, an NFC/Sub-GHz security toolkit, an off-grid BSAF disaster-alert receiver, an SDR wideband receiver, and a LAN diagnostics tool.

> **Status (2026-11-17): hardware arrived, verification started.** The CardputerZero, Cap LoRa-1262 and Cap CC1101 have arrived, and their Japanese radio certifications have been checked against the official database. This repository contains the design specification and some early implementations. Implementation of each app will proceed once the open items in [HANDOFF §9](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo) are verified on the device.

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
| OS | Raspberry Pi OS (Debian Linux) |
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

Cap A and Cap B share the same top-slot connector and cannot be mounted simultaneously.

### Companion Hardware (recommended add-ons)

| Device | Role |
|---|---|
| [M5Stack C6L Meshtastic Unit](https://www.switch-science.com/products/10809) | Home-side LoRa gateway (Internet ↔ Meshtastic bridge, Wi-Fi 6 built-in) |
| [M5Stack Chain Encoder × 2](https://www.switch-science.com/collections/m5stack/products/10919) | Daisy-chained rotary knobs (frequency tuning / list scrolling) |
| [RTL-SDR Blog V4](https://www.rtl-sdr.com/rtl-sdr-blog-v4-dongle-initial-release/) | USB SDR dongle for 500 kHz – 1.75 GHz wideband reception |

---

## Planned Applications

| ID | App | Priority | Hardware | Primary Function |
|---|---|---|---|---|
| 01 | `gps-logger` | ★★★★★ | Cap A | GPX track logger + sky plot view of visible GNSS satellites |
| 02 | `lora-mesh-node` | ★★★★☆ | Cap A + C6L gateway | Meshtastic-compatible off-grid messaging node |
| 03 | `nfc-toolkit` | ★★★★☆ | Cap B | NFC card learning tool (ISO 14443A/B, FeliCa, ISO 15693) |
| 04 | `subghz-sniffer` | ★★★☆☆ | Cap B | Sub-GHz signal analyzer (receive-only in Japan) |
| 05 | `bsaf-client` | ★★★★☆ | Cap A + Wi-Fi | Two-channel ([BSAF v1](https://github.com/osprey74/bsaf-protocol)) disaster alert receiver (MQTT primary, LoRa fallback) |
| 06 | `edge-ai` | ★★★☆☆ | Built-in | Offline LLM assistant (quantized 1B-parameter models) |
| 07 | `wifi-analyzer` | ★★★☆☆ | Built-in | Wi-Fi environment scanner and analyzer |
| 08 | `nfc-checkpoint` | ★★★☆☆ | Cap A + Cap B | NFC tag + GPS waypoint checkpoint logger |
| 09 | `nfc-lora-auth` | ★★☆☆☆ | Cap A + Cap B | Off-grid badge auth PoC (NFC scan → LoRa relay) |
| 10 | `sdr-receiver` | ★★★★☆ | RTL-SDR V4 | Wideband SDR receiver + integrated spectrum monitor (FM / ADS-B / AIS / NOAA APT / rtl_433) |
| 11 | `lan-scanner` | ★★★★☆ | Built-in | Pocket-sized network diagnostics tool (nmap / arp-scan, Wi-Fi + Ethernet) |

Each app's full feature checklist is in [HANDOFF §3](./HANDOFF_cardputerzero.md#3-アプリ開発仕様).

---

## Tech Stack

- **Language**: Rust (primary), Python (sidecars and tooling)
- **UI Framework**: [LVGL](https://lvgl.io/) via [CardputerZero-AppBuilder](https://github.com/m5stack/CardputerZero-AppBuilder) (`czdev` CLI)
- **Target Triple**: `aarch64-unknown-linux-gnu`
- **Emulator**: `czdev run` (SDL2-based, reproduces the 320×170 LCD on a development machine)
- **Deployment**: SSH + `scp` to the device (the username is chosen in the first-boot setup)
- **App Distribution**: `czdev upload` to the official Debian apt repository at [m5stack/CardputerZeroRepository](https://github.com/m5stack/CardputerZeroRepository) — end users install via `apt install`
- **Remote Development**: Tailscale VPN ↔ home Mac Mini for running full Claude models off-device (the 512MB RAM is too small for local LLM hosting)

---

## Repository Structure

```
cardputerzero-apps/
├── CLAUDE.md
├── HANDOFF_cardputerzero.md   # Primary design specification
├── apps/
│   ├── gps-logger/            # App 01 [Cap A]
│   ├── lora-mesh-node/        # App 02 [Cap A]
│   ├── nfc-toolkit/           # App 03 [Cap B]
│   ├── subghz-sniffer/        # App 04 [Cap B]
│   ├── bsaf-client/           # App 05 [Cap A + Wi-Fi]
│   ├── edge-ai/               # App 06 [built-in]
│   ├── wifi-analyzer/         # App 07 [built-in]
│   ├── nfc-checkpoint/        # App 08 [Cap A + Cap B alternating]
│   ├── nfc-lora-auth/         # App 09 [Cap A + Cap B alternating]
│   ├── sdr-receiver/          # App 10 [RTL-SDR USB]
│   └── lan-scanner/           # App 11 [built-in Wi-Fi / Ethernet]
├── shared/
│   ├── lora_sx1262/           # SX1262 LoRa driver [Cap A]
│   ├── gnss_at6668/           # AT6668 GNSS driver [Cap A]
│   ├── nfc_st25r3916/         # ST25R3916 NFC driver [Cap B]
│   ├── rf_cc1101/             # CC1101 Sub-GHz driver [Cap B]
│   ├── input_encoder/         # Chain Encoder shared input driver [Grove UART]
│   └── ui_theme/              # Shared LVGL theme
└── scripts/
    ├── setup_device.sh        # initial device setup
    ├── setup_rtlsdr.sh        # RTL-SDR V4 driver setup (App 10)
    ├── swap_cap_a.sh          # Cap A device path helper
    ├── swap_cap_b.sh          # Cap B device path helper
    └── deploy_all.sh          # bulk deploy helper
```

---

## Getting Started

> ⚠️ Implementation has not started. The steps below describe the planned development workflow once the hardware arrives.

### Development Machine

This project officially supports macOS, Linux, and **Windows 11 via MSYS2 MINGW64** (per AppBuilder's `DESKTOP_DEV.md`).

```bash
# 1. Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add aarch64-unknown-linux-gnu

# 2. Install SDL2 for the czdev emulator
#    macOS:        brew install sdl2 sdl2_image sdl2_mixer
#    Linux:        sudo apt install libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev
#    Windows 11:   pacman -S mingw-w64-x86_64-SDL2 mingw-w64-x86_64-SDL2_image mingw-w64-x86_64-SDL2_mixer
#                  (run inside the MSYS2 MINGW64 shell)

# 3. Clone and build CardputerZero-AppBuilder
git clone --recursive https://github.com/m5stack/CardputerZero-AppBuilder.git
cd CardputerZero-AppBuilder
cargo build --release -p czdev
export PATH="$PATH:$(pwd)/target/release"

# 4. Smoke-test the emulator
czdev run examples/hello_cz
```

Full setup including device-side initialization (gpsd, SPI, UART enablement) is documented in [HANDOFF §6](./HANDOFF_cardputerzero.md#6-開発環境セットアップ).

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
