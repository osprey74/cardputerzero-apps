# rust-sdl2-app — CardputerZero アプリ雛形（Rust / SDL2）

SDL2 でウィンドウ/画面へ描く CardputerZero アプリの型。方針は [HANDOFF §2.7.6【確定】](../../HANDOFF_cardputerzero.md) 準拠（`legacy-deb-only` スタンドアロン・ネイティブバイナリ）。

- **画面サイズは 320×170 厳守**（`W`/`H` 定数・CardputerZero LCD 実解像度）
- 描画は AA 無し・等倍（`src/draw.rs`: 点=塗り四角 / 線 / 円 / 8×8 文字）
- `framebuffer` 直叩きの [rust-fb-app](../rust-fb-app/) と選択で使い分け（SDL2 はイベント/キーボード/音が必要な UI 向け）

## 構成

```
rust-sdl2-app/
├── app-builder.json          # runtime:"legacy-deb-only"
├── Cargo.toml                # sdl2 / libc
├── src/main.rs               # 320×170 ウィンドウ・デモ描画・スクショ/SIGTERM
├── src/draw.rs               # 描画ヘルパー（fill_square/line/circle/text）
├── src/font8x8.rs            # public-domain 8×8 フォント（機械生成）
└── packaging/                # meta.env / build.sh / stage.sh / postinst
```

## ビルド & 配布

```bash
# .deb 生成（成果物: apps/<app>/dist-cz/*.deb）
scripts/pack_deb.sh apps/<your-app>
# 生成 + デバイスへ
CZ_HOST=pi@<ip> scripts/deploy.sh apps/<your-app>
# 実機上でネイティブビルド（SDL2 クロスは sysroot が要るため実機ビルドが簡単）
CZ_TARGET= scripts/pack_deb.sh apps/<your-app>
```

前提: ビルドに `libsdl2-dev` + `pkg-config`、実行に `libsdl2-2.0-0`（.deb の Depends に記載済み）。

## ヘッドレス検証（表示装置なしでスクショ）

```bash
SDL_VIDEODRIVER=dummy CZ_SCREENSHOT=/tmp/shot.bmp ./target/release/cz-hello-sdl2
# → /tmp/shot.bmp に 1 フレーム保存して終了。CI や SSH 越し検証に使う。
# ※ dummy は常時利用可。offscreen ドライバは SDL のビルドによっては無い（2.0.14 では不可）。
```

## 実機実証

uConsole(aarch64) で `libsdl2-dev` 導入 → ネイティブビルド → offscreen スクショ生成まで確認済み
（詳細は HANDOFF 変更履歴 2026-07-08）。実 CZ での LCD 出力ドライバ（KMSDRM/fbdev）は実機到着後に確定。
