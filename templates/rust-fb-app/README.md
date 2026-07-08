# rust-fb-app — CardputerZero アプリ雛形（Rust / framebuffer）

CardputerZero 向けアプリの**標準の型**。方針は [HANDOFF §2.7.6【確定】](../../HANDOFF_cardputerzero.md) に準拠する。

- **形式**: `legacy-deb-only` の**スタンドアロン・ネイティブ実行バイナリ**（`lvgl-dlopen` は使わない）
- **描画**: `/dev/fb0` 直描画（X / Wayland / LVGL ホスト不要）。`APPLAUNCH_LINUX_FBDEV_DEVICE` を尊重
- **言語**: Rust（第一候補）。C はフォールバック、本質 Python なサイドカーは Python で別枠
- **配布**: 非公開ローカルのみ（公式 AppStore へは公開しない）

## ディレクトリ構成

```
rust-fb-app/
├── app-builder.json      # runtime:"legacy-deb-only" を明示（公式ツール互換のメタ）
├── Cargo.toml            # package.name = バイナリ名 = PKG_NAME
├── src/main.rs           # framebuffer 直描画・SIGTERM で終了
└── packaging/
    ├── meta.env          # PKG_NAME / APP_NAME / APP_ICON など（.deb と APPLaunch 登録）
    ├── build.sh          # cargo build（既定は aarch64 クロス）→ .czbuild/ へ
    ├── stage.sh          # 成果物を $INSTALL_PREFIX/bin/ へ install
    └── postinst          # video/input/render グループへ pi を追加
```

## 新規アプリの作り方

1. このディレクトリを `apps/<your-app>/` へコピー
2. `Cargo.toml` の `name`、`app-builder.json`、`packaging/meta.env` の `PKG_NAME`/`APP_NAME`/`APP_EXEC`/`APP_ICON` を書き換え（**3 箇所の名前を一致させる**）
3. `src/main.rs` を実装（`app-builder.json` の `caps` に使う機能を宣言）
4. アイコンを `assets/icon.png`（48x48 PNG）として置く（任意）

## ビルド & 配布（開発機から）

```bash
# .deb 生成のみ（成果物: apps/<app>/dist-cz/*.deb）
scripts/pack_deb.sh apps/<your-app>

# 生成 + デバイスへ転送・インストール
CZ_HOST=pi@<device-ip> scripts/deploy.sh apps/<your-app>

# 実機上でネイティブビルドする場合（クロスしない）
CZ_TARGET= scripts/pack_deb.sh apps/<your-app>
```

公式ツールを使う場合は `czdev deploy --host pi@<ip> --deb <pkg>.deb` でも可。

## 前提・未確認事項

- **開発機に `dpkg-deb` が必要**（Debian/Ubuntu/MSYS2 等）。クロスビルドには
  `rustup target add aarch64-unknown-linux-gnu` と aarch64 リンカ。
- ⚠️ **Windows 開発機では framebuffer クレートがビルド不可**（Linux 専用）。実機到着まで
  **uConsole 等 aarch64 Linux でネイティブビルド・検証**する（`CZ_TARGET=`）。
- ⚠️ 本雛形は**未ビルド検証**（実機/aarch64 環境が手元にないため）。初回検証で fbdev の
  bpp（16/32）・APPLaunch の `.desktop` 認識パスを確定し、HANDOFF §9 TODO を更新する。
- ⚠️ APPLaunch がホーム画面に載せる登録ファイルの**正確なパス/形式は実機未確認**。
  `pack_deb.sh` は暫定で XDG `.desktop` を置いている。
