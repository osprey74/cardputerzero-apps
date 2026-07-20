# App 16 星座盤 (`stellar-map`)

CardputerZero (Raspberry Pi CM0 / Linux) 向けの**オフライン星座盤**。指定した日時・観測地点の
恒星・星座線・深宇宙天体・惑星・月を 1.9" LCD (320×170) に描く。設計の一次資料は
[`../../HANDOFF_cardputerzero.md`](../../HANDOFF_cardputerzero.md) §3 App 16。

![スクリーンショット](docs/screenshot.png)

> 実機（uConsole・2026-07-20）でのライブ表示。地磁気（BMM150）で自機の向きを画面上に固定して
> 全天図を回転（方式A・N/S/E/W が現在の向きに追従）、惑星（Mercury/Jupiter/Venus）と月相を表示。

## アーキテクチャ（Python サイドカー ＋ Rust/LVGL UI）

天体計算・投影・色/サイズ決定は**すべて Python 側**で行い、320×170 の**デバイス座標
プリミティブ（Scene）**に落として JSON で渡す。UI（Rust/LVGL）は Scene を受け取り
**四角・線・文字を描くだけ**の薄い実装にする。

```
[HYG/OpenNGC/Stellarium 中間形式]  [Skyfield + DE421]
            │                            │
            └──────────┬─────────────────┘
                       ▼
   sidecar/stellar_sidecar.py  ── Scene JSON (1行/フレーム・JSON Lines) ──▶  ui/ (Rust/LVGL)
   (時刻=RTC/NTP/GNSS, 位置=GNSS,                                          「描くだけ」
    方位=CoreS3 BMM150)
```

- **共通コア** [`shared/star_catalog`](../../shared/star_catalog/): カタログ読込・座標変換・
  `build_scene()`（Scene 生成）。
- **サイドカー** [`sidecar/stellar_sidecar.py`](sidecar/stellar_sidecar.py): Scene を JSON Lines で stdout 出力。
- **前処理/検証** [`tools/`](tools/): データ取込ツール群と PC 検証レンダラ
  （`render_catalog.py` = 直接描画 / `render_scene.py` = Scene JSON から描画してプロトコル検証）。
- **UI** [`ui/`](ui/): czdev/LVGL の Rust アプリ（**scaffold・czdev 到着後にビルド**）。

## Scene JSON プロトコル（サイドカー → UI の契約）

1 フレーム = 1 行の JSON。座標は 320×170 の整数デバイス画素。地平線下の要素は含まない
（UI は素直に描くだけ）。

```jsonc
{
  "w":320, "h":170,
  "chrome": { "circle":[85,85,80], "circle_color":[60,66,70],
              "dir_color":[255,165,0], "dirs":[[x,y,"N"], ...] },
  "lines": [[x1,y1,x2,y2], ...],           // 星座線
  "line_color": [40,90,110],
  "points": [[x,y,side,r,g,b], ...],       // 星/DSO/惑星/月（side=四角の一辺 px）
  "labels": [[x,y,"Vega",r,g,b], ...],     // 天体名
  "meta": { "time_local":"...", "lat":.., "lon":..,
            "moon":{"frac":..,"waxing":..,"phase":".."},
            "counts":{"stars":..,"lines":..,"dso":..,"planets":..} }
}
```

描画順（UI）: `chrome`(円+方位) → `lines` → `points`(配列順=DSO→星→惑星→月) → `labels` → 情報パネル(`meta`)。
描画方針は **四角ドット＋AA 無し＋等倍**（低解像度 LCD で最も鮮明・HANDOFF §App16 決定）。

## 使い方（PC・実機なしで検証）

```bash
pip install -r tools/requirements.txt          # Pillow + skyfield

# 1) データ取込（HYG/OpenNGC/Stellarium・自動DL・生成物は非コミット）
python tools/build_star_catalog.py
python tools/build_constellations.py
python tools/build_dso.py

# 2) サイドカー → Scene JSON → PNG（プロトコル検証）
python sidecar/stellar_sidecar.py --dt 2026-07-08T03:30 | python tools/render_scene.py

# 直接描画版（モード比較・四角/AA無し等）
python tools/render_catalog.py --shape square --no-aa
```

## UI キー割当（実機 SDL2）

| キー | 動作 |
| --- | --- |
| `L` | 星座線 表示 ON/OFF（既定 ON） |
| `D` | DSO（深宇宙天体）表示 ON/OFF（既定 ON） |
| `P` | 惑星・月の名前 表示 ON/OFF（既定 ON） |
| `C` | 星座名 表示 ON/OFF（既定 OFF・低解像度での混雑回避） |
| `S` | スクリーンショット PNG 保存（`STELLAR_SHOTS_DIR` → `$HOME/stellar_shots`） |

## Chain Encoder 操作（星座 / 惑星・月 のリスト・拡大表示）

5 モードの状態機械（サイドカー側）。赤起点＝星座系、青起点＝惑星系で対称。

**星座（赤起点）**

| 操作 | 動作 |
| --- | --- |
| 星座盤で **赤 押込** | 星座リスト（IAU略号＋ラテン名・`up`/`--`＝地平線上か） |
| リストで **赤 回転** | カーソル移動（感度 `enc_sensitivity`） |
| リストで **青 押込** | その星座を「今見えている角度で」拡大表示 |
| 拡大表示で **青 回転** | 拡大／縮小（目印星も同倍率） |
| 拡大表示で **青 押込** | リストへ戻る |
| リストで **赤 押込** | 星座盤へ戻る |

**惑星・月・1等星（青起点・星座と逆操作）**

| 操作 | 動作 |
| --- | --- |
| 星座盤で **青 押込** | 惑星・月・1等星リスト（`up`/`--` 付き） |
| リストで **青 回転** | カーソル移動 |
| リストで **赤 押込** | その天体を中心に拡大表示 |
| 拡大表示で **赤 回転** | 拡大／縮小 |
| 拡大表示で **赤 押込** | リストへ戻る |
| リストで **青 押込** | 星座盤へ戻る |

- 拡大表示（星座/天体とも）では、探す目安として周囲の**明るい星（1等星＝3×3十字 / 2等星＝1ドット）**、および**天球外周円＋方角 N/S/E/W**（画面端にコンパス表示）を重ねる。
- 1等星が星座に属する場合、その拡大表示で**星座線と星座名**も表示する。

## キーボード操作（Chain Encoder 非接続時・CardputerZero 単体）

Chain Encoder が無くてもキーボードで同じ状態遷移ができる（UI がサイドカーを子プロセス
起動し、キー操作を stdin で送る運用＝launcher の子プロセス起動モード）。

| キー | 動作 |
| --- | --- |
| `Enter` | 一段深く（星座盤→星座リスト / リスト→拡大表示） |
| `Tab` | 星座盤→惑星・月・1等星リスト |
| `↑` / `↓` | リストでカーソル移動 / 拡大表示で拡大・縮小（↑=拡大） |
| `Esc` | 一段戻る（拡大→リスト→星座盤） |

レイヤトグル `L`/`D`/`P`/`C`・スクショ `S` はどちらの運用でも有効。

方位は地磁気（BMM150）で自機の向きを画面上に固定（方式A）。個体・取付依存の較正／姿勢
オフセットは `~/.config/cardputerzero/stellar_map.json`（例 `config/stellar_map.json.example`）。

## 状態

| 部位 | 状態 |
| --- | --- |
| データ取込（HYG/OpenNGC/星座線） | ✅ 完了（PC 検証済み） |
| 天体計算（Skyfield 惑星/月/月相） | ✅ 完了（PC 検証済み） |
| Scene プロトコル＋サイドカー | ✅ 完了（`render_scene.py` で PC 実証） |
| Rust/LVGL UI | 🚧 **scaffold**（czdev 未導入・実機未到着のためビルド未）。`ui/` にプリミティブ描画の骨組み |
| RTC/NTP/GNSS 時刻・位置入力、HDMI 切替、BMM150 方位較正 | ⬜ 実機到着後 |

> czdev（SDL2 エミュレータ / AppBuilder）は Kickstarter 配布物で未入手。到着後に `ui/` の
> LVGL 描画呼び出しを czdev API に合わせて確定し、`czdev run`（PC エミュレータ）→ 実機の順で検証する。
