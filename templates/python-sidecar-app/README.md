# python-sidecar-app — CardputerZero アプリ雛形（Python サイドカー）

重い計算（天体・センサ・カメラ・ネットワーク等）を Python 側で行い、**320×170 のデバイス座標
プリミティブを JSON Lines（1 行 1 フレーム）で stdout に吐く**サイドカーの型。UI は
[rust-sdl2-app](../rust-sdl2-app/) 派生の薄い front-end がこれを読んで描く。方針は
[HANDOFF §2.7.6【確定】](../../HANDOFF_cardputerzero.md) 準拠（`legacy-deb-only` Python）。

- 本質的に Python なもの（Skyfield/picamera2/pyzbar 等）はコンパイルせず Python のまま配布
- 実例: 星座盤 App16 の `apps/stellar-map/sidecar/stellar_sidecar.py`（Scene プロトコル）

## フレーム schema（UI との契約・320×170 整数画素）

```jsonc
{
  "w": 320, "h": 170, "t": 1.23,
  "points": [[x, y, side, r, g, b]],   // 一辺 side px の塗り四角
  "labels": [[x, y, "text", r, g, b]], // 8×8 文字列
  "meta":   { }                        // UI が情報表示に使う任意データ
}
```

## 使い方

```bash
python3 sidecar.py                 # 1 フレーム出力して終了
python3 sidecar.py --interval 0.1  # 0.1 秒ごとに出し続ける（JSON Lines）
python3 sidecar.py --frames 50     # 50 フレームで終了
python3 sidecar.py | <ui-binary>   # UI へパイプ
```

## ビルド & 配布

```bash
scripts/pack_deb.sh apps/<your-app>              # .deb 生成（py_compile 構文チェック込み）
CZ_HOST=pi@<ip> scripts/deploy.sh apps/<your-app>
```

前提: 実行に `python3`（.deb の Depends に記載）。追加の Python 依存は `meta.env` の
`PKG_DEPENDS` に `python3-xxx` を足すか、`requirements.txt`＋postinst で venv を作る。
