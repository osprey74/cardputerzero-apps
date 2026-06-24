#!/usr/bin/env bash
# setup_rtlsdr.sh — RTL-SDR Blog V4 (R828D / USB-C) 専用ドライバセットアップ
#
# 標準の "rtl-sdr" パッケージは V4 の R828D チューナーに対応していないため、
# rtlsdrblog 公式リポジトリからビルドして導入する必要がある。
# 詳細: HANDOFF_cardputerzero.md §3 App 10 ステップ 0-2
#
# 対象 OS: Raspberry Pi OS / Debian 11+ (uConsole / CardputerZero 共通)
#
# 実行方法 (uConsole 上、ドングル未接続の状態で):
#     bash scripts/setup_rtlsdr.sh
#     (途中で sudo パスワード入力あり)
# 完了後、必ず再起動 → 再起動後にドングルを USB-C ポートに接続 → rtl_test -t で確認

set -euo pipefail

readonly REPO_URL="https://github.com/rtlsdrblog/rtl-sdr-blog.git"
readonly BLACKLIST_FILE="/etc/modprobe.d/blacklist-rtlsdr.conf"
readonly BUILD_DIR="${HOME}/rtl-sdr-blog"

log()  { printf '\033[1;36m[%s]\033[0m %s\n' "setup_rtlsdr" "$*"; }
warn() { printf '\033[1;33m[%s]\033[0m %s\n' "setup_rtlsdr" "$*" >&2; }

if ! command -v sudo >/dev/null 2>&1; then
    warn "sudo が見つかりません。本スクリプトは sudo を必要とします。"
    exit 1
fi

log "対象: $(. /etc/os-release && echo "${PRETTY_NAME}") / $(uname -m)"
log "RTL-SDR Blog V4 ドングルが現在 USB に接続されていないことを確認してください。"
read -r -p "続行しますか? [y/N] " ans
[[ "${ans}" =~ ^[Yy]$ ]] || { log "中止しました。"; exit 0; }

# ─── ステップ 0: 既存ドライバの除去 + DVB ブラックリスト + ビルド依存 ─────
log "[Step 0] 既存 rtl-sdr パッケージを除去します (apt purge)"
if dpkg -l rtl-sdr 2>/dev/null | grep -q '^ii'; then
    sudo apt-get purge -y rtl-sdr librtlsdr0 librtlsdr-dev 2>/dev/null || true
    sudo apt-get autoremove -y
else
    log "  → 既存 rtl-sdr 無し、スキップ"
fi

log "[Step 0] DVB ドライバを modprobe ブラックリスト登録"
sudo tee "${BLACKLIST_FILE}" > /dev/null <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
log "  → ${BLACKLIST_FILE} 更新済み"

log "[Step 0] initramfs を更新 (ブラックリスト反映)"
sudo update-initramfs -u

log "[Step 0] ビルド依存パッケージをインストール"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    git cmake build-essential libusb-1.0-0-dev pkg-config

# ─── ステップ 1: rtlsdrblog 公式ドライバのビルド・インストール ────────
log "[Step 1] rtlsdrblog 公式リポジトリを clone (${BUILD_DIR})"
if [[ -d "${BUILD_DIR}/.git" ]]; then
    log "  → 既存 clone を更新"
    git -C "${BUILD_DIR}" pull --ff-only
else
    rm -rf "${BUILD_DIR}"
    git clone --depth=1 "${REPO_URL}" "${BUILD_DIR}"
fi

log "[Step 1] ビルド + インストール"
cd "${BUILD_DIR}"
rm -rf build && mkdir build && cd build
cmake .. -DINSTALL_UDEV_RULES=ON
make -j"$(nproc)"
sudo make install
sudo ldconfig

log "[Step 1] udev ルールを反映"
sudo cp ../rtl-sdr.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

# ─── 完了メッセージ ──────────────────────────────────────────
cat <<'EOF'

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ RTL-SDR Blog V4 ドライバのインストール完了

次の手順 (重要):
  1) sudo reboot         ← ブラックリストとドライバを確実に反映させるため必須
  2) 再起動後に RTL-SDR Blog V4 ドングルを USB-C ポートへ接続
     (現在 dvb_usb_rtl28xxu が掴まないように、必ず再起動が先)
  3) rtl_test -t         ← 認識確認
     成功時の出力例:
       Found 1 device(s):
         0:  Realtek, RTL2838UHIDIR, SN: 00000001
       Using device 0: Generic RTL2832U OEM
       Found Rafael Micro R828D tuner    ← R828D と表示されれば本物の V4
  4) rtl_fm -M wbfm -f 80.4e6 - | aplay -r 32000 -f S16_LE
     (試しに NHK FM 札幌 80.4 MHz を聴く / aplay でリアルタイム再生)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
