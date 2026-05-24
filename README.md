# CardputerZero Apps

> Application monorepo for the [M5Stack CardputerZero](https://shop.m5stack.com/pages/m5-cardputerzero) — a credit-card-sized Linux handheld powered by Raspberry Pi CM0.

[日本語版 README はこちら](./README.ja.md)

This repository hosts seven planned applications for the CardputerZero, ranging from a GPS logger and LoRa Meshtastic node to NFC and Sub-GHz learning tools, an offline BSAF disaster-alert receiver, an edge AI assistant, and a Wi-Fi analyzer.

> **Status (2026-05-24): pre-hardware.** The CardputerZero is a Kickstarter project and the physical device has not yet shipped. This repository currently contains the design specification and skeleton structure. Implementation will begin once the hardware arrives and the open items in [HANDOFF §9](./HANDOFF_cardputerzero.md#9-既知の未確認事項todo) are verified on the device.

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

Full hardware spec sheet is in [HANDOFF §1](./HANDOFF_cardputerzero.md#1-ハードウェア概要).

---

## Planned Applications

| ID | App | Priority | Primary Function |
|---|---|---|---|
| 01 | `gps-logger` | ★★★★★ | GPX track logger using the AT6668 GNSS chip on Cap LoRa 1262 |
| 02 | `lora-mesh-node` | ★★★★☆ | Meshtastic-compatible off-grid messaging node (SX1262) |
| 03 | `nfc-toolkit` | ★★★★☆ | NFC card learning tool (ST25R3916, ISO 14443A/B, FeliCa, ISO 15693) |
| 04 | `subghz-sniffer` | ★★★☆☆ | Sub-GHz signal analyzer (CC1101, receive-only in Japan) |
| 05 | `bsaf-client` | ★★★★☆ | Off-grid receiver for [BSAF v1](https://github.com/osprey74/bsaf-protocol) disaster alerts |
| 06 | `edge-ai` | ★★★☆☆ | Offline LLM assistant (quantized 1B-parameter models) |
| 07 | `wifi-analyzer` | ★★★☆☆ | Wi-Fi environment scanner and analyzer |

Each app's feature checklist lives in [HANDOFF §3](./HANDOFF_cardputerzero.md#3-アプリ開発仕様).

---

## Tech Stack

- **Language**: Rust (primary), Python (sidecars and tooling)
- **UI Framework**: [LVGL](https://lvgl.io/) (Light and Versatile Graphics Library) via [CardputerZero-AppBuilder](https://github.com/m5stack/CardputerZero-AppBuilder) (`czdev` CLI)
- **Target Triple**: `aarch64-unknown-linux-gnu`
- **Emulator**: `czdev run` (SDL2-based, reproduces the 320×170 LCD on a development machine)
- **Deployment**: SSH + `scp` to `pi@cardputerzero.local`
- **App Distribution**: PR-based registration to [cardputerzero.github.io](https://cardputerzero.github.io)

---

## Repository Structure

```
cardputerzero-apps/
├── CLAUDE.md
├── HANDOFF_cardputerzero.md   # Primary design specification
├── apps/
│   ├── gps-logger/            # App 01
│   ├── lora-mesh-node/        # App 02
│   ├── nfc-toolkit/           # App 03
│   ├── subghz-sniffer/        # App 04
│   ├── bsaf-client/           # App 05
│   ├── edge-ai/               # App 06
│   └── wifi-analyzer/         # App 07
├── shared/
│   ├── lora_sx1262/           # SX1262 LoRa driver
│   ├── gnss_at6668/           # AT6668 GNSS driver
│   └── ui_theme/              # Shared LVGL theme
└── scripts/
    ├── setup_device.sh        # (planned) initial device setup
    └── deploy_all.sh          # (planned) bulk deploy helper
```

---

## Getting Started

> ⚠️ Implementation has not started. The steps below describe the planned development workflow once the hardware arrives.

### Development Machine (macOS or Windows 11)

```bash
# 1. Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add aarch64-unknown-linux-gnu

# 2. Install SDL2 for the czdev emulator
#    macOS:
brew install sdl2 sdl2_image sdl2_mixer
#    Windows 11: use WSL2 (Ubuntu) and run the apt commands inside it

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

All radio-frequency features ship with deliberate constraints for Japanese law compliance. In particular:

- **LoRa transmission**: 920MHz band only, on certified (技適-approved) modules
- **Sub-GHz**: CC1101 used for receive only; no transmission without proper certification
- **NFC**: card emulation and UID writing restricted to user-owned cards for educational use
- **Wi-Fi analysis**: targets restricted to user-owned access points

Details and citations are in [HANDOFF §7](./HANDOFF_cardputerzero.md#7-日本国内の法令技術基準).

---

## Ecosystem Integration

- **[Rindo](https://github.com/osprey74/Rindo-iOS)** — GPX exports from `gps-logger` (App 01) are designed to be imported into the Rindo cycling navigation app
- **[bsaf-protocol](https://github.com/osprey74/bsaf-protocol)** — `bsaf-client` (App 05) conforms to the BSAF v1 specification
- **bsaf-jma-bot** — App 05 subscribes to the BSAF MQTT feed when Wi-Fi is available, falling back to LoRa otherwise

---

## License

License terms are to be determined once the project moves out of the design phase. Until then, all rights are reserved by the author.

---

## Links

- **Kickstarter**: https://www.kickstarter.com/projects/m5stack/cardputerzero
- **M5Stack Official Store**: https://shop.m5stack.com/pages/m5-cardputerzero
- **CardputerZero-AppBuilder**: https://github.com/m5stack/CardputerZero-AppBuilder
- **App Store Hub**: https://cardputerzero.github.io
- **Cap LoRa 1262 Module**: https://shop.m5stack.com/products/cap-lora-1262-for-cardputer-adv-sx1262-atgm336h

---

## Author

**osprey74 (Sohshi)** — Bluesky: [@osprey74.bsky.social](https://bsky.app/profile/osprey74.bsky.social)
