#!/usr/bin/env bash
# pack_deb.sh <app-dir> — packaging/{meta.env,build.sh,stage.sh,postinst} から .deb を生成する。
#
# 非公開ローカル配布用の自前パッカー（公式 AppBuilder CI の pack_deb.py 相当を手元で再現）。
# HANDOFF §2.7.6【確定】: legacy-deb-only スタンドアロンバイナリを非公開配布する方針。
#
# 出力: <app-dir>/dist-cz/<pkg>_<ver>-<rev>_<arch>.deb
#       診断は stderr、生成した .deb のパスのみ stdout 最終行に出す（deploy.sh が拾う）。
#
# 依存: dpkg-deb（開発機に要インストール）。実機ネイティブビルドは CZ_TARGET= を指定。
set -euo pipefail

APP_DIR="${1:?usage: pack_deb.sh <app-dir>}"
APP_DIR="$(cd "$APP_DIR" && pwd)"
cd "$APP_DIR"
[ -f packaging/meta.env ] || { echo "no packaging/meta.env in $APP_DIR" >&2; exit 1; }

# meta.env を読み込み（以降の子スクリプトへも export）
set -a
# shellcheck disable=SC1091
. packaging/meta.env
set +a
: "${PKG_NAME:?meta.env に PKG_NAME が必要}"
: "${PKG_VERSION:?meta.env に PKG_VERSION が必要}"
PKG_REVISION="${PKG_REVISION:-osprey74-1}"
ARCH="${PKG_ARCH:-arm64}"
INSTALL_PREFIX="${INSTALL_PREFIX:-/usr/share/APPLaunch}"
export PKG_NAME PKG_VERSION PKG_REVISION INSTALL_PREFIX

echo "[pack_deb] build $PKG_NAME $PKG_VERSION ($ARCH)" >&2
[ -f packaging/build.sh ] && bash packaging/build.sh

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"   # mktemp 既定の 0700 だとパッケージ root が 700 になるため
export STAGE
echo "[pack_deb] stage -> $STAGE" >&2
bash packaging/stage.sh

# DEBIAN/control
mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $PKG_VERSION-$PKG_REVISION
Architecture: $ARCH
Maintainer: osprey74
Depends: ${PKG_DEPENDS:-}
Description: ${PKG_DESC:-${APP_NAME:-$PKG_NAME}}
EOF

# postinst（あれば）
if [ -f packaging/postinst ]; then
  install -m 0755 packaging/postinst "$STAGE/DEBIAN/postinst"
fi

# APPLaunch 登録用 .desktop
# ⚠️ APPLaunch が読む正確なパス/形式は実機未確認（HANDOFF §9 TODO）。
#    暫定で XDG .desktop を $INSTALL_PREFIX/share/applications に置く。
if [ -n "${APP_NAME:-}" ]; then
  DESK="$STAGE$INSTALL_PREFIX/share/applications/$PKG_NAME.desktop"
  mkdir -p "$(dirname "$DESK")"
  cat > "$DESK" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Exec=${APP_EXEC:-$INSTALL_PREFIX/bin/$PKG_NAME}
Icon=${APP_ICON:-$PKG_NAME}
Terminal=${APP_TERMINAL:-false}
Categories=Utility;
EOF
fi

OUT_DIR="${DEB_OUT:-$APP_DIR/dist-cz}"
mkdir -p "$OUT_DIR"
DEB="$OUT_DIR/${PKG_NAME}_${PKG_VERSION}-${PKG_REVISION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >&2
echo "[pack_deb] wrote $DEB" >&2

# stdout には .deb パスのみ（deploy.sh が受け取る）
echo "$DEB"
