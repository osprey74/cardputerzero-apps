# App 16 星座盤 ― データ前処理ツール

HYG 星表を取り込み、実行時に高速ロードできる軽量な中間形式へ変換するツール群。

## ⚠️ データとライセンス

- **HYG Database v4.1**（© astronexus・**CC BY-SA 4.0**：表示＋継承）を使用。
- 生データ（`data/raw/hygdata_v41.csv`・約 34MB）も生成物（`data/stars.bin` 等）も
  **リポジトリにはコミットしない**（`apps/stellar-map/data/.gitignore`）。本ツールが
  都度ダウンロード・生成する。生成データを再配布する際は CC BY-SA 4.0 を維持し出典明記。
- 出典 URL: <https://github.com/astronexus/HYG-Database>

## `build_star_catalog.py` ― 取込・前処理

HYG CSV から**裸眼可視（既定 等級 ≤ 6.5・約 8,900 星）**を抽出し、コンパクトな
中間形式を `data/` に生成する。CSV が無ければ自動ダウンロードする。

```bash
python build_star_catalog.py                 # 既定 等級<=6.5・data/ に出力
python build_star_catalog.py --mag-limit 5.0
python build_star_catalog.py --out-dir /mnt/sdcard/stellar_map/data
```

生成物:

| ファイル | 内容 |
| --- | --- |
| `stars.bin` | 1 星 20 バイト固定長・LE・等級昇順。`<iffff` = hip(int32), ra_deg(f32), dec_deg(f32), mag(f32), ci(f32) |
| `stars_meta.json` | 件数・等級上限・出典・ライセンス・レコード仕様 |
| `named_stars.json` | 固有名 → インデックス（ラベル・検索用） |

- HYG の `ra` は「時」なので度へ換算（×15）して格納。
- `hip` は星座線（Stellarium）参照キー。無しは `-1`。太陽（id=0）は除外。
- 実績: 等級 ≤ 6.5 で **8,920 星 / 固有名 357 件**、`stars.bin` は約 174KB。

## `render_catalog.py` ― 可視検証

生成した中間形式を `shared/star_catalog` 経由でロードし、320×170 の全天図に描画して
PNG 出力する（取込が正しいかの目視検証・惑星/月/星座線は次段）。

```bash
python render_catalog.py                      # 札幌 2026-07-07 21:30 JST・view mag<=4.5
python render_catalog.py --mag-view 4.0 --dt 2026-12-01T22:00 --lat 35.68 --lon 139.77
```

- `--mag-view`：**描画時**の上限等級（カタログは全星保持したまま暗い星を間引く）。
- `--shape round|square`：星の形。`square`=四角ドット。
- `--no-aa`：**等倍・AA 無し**で描画（文字は bilevel、四角はピクセル正確）。**実機 LCD の見えに最も近い**。
  - 未指定（既定）は SS=4 のスーパーサンプリングで丸を滑らかに描く（PC プレビュー向き）。
  - `--out` 未指定時は `hyg_<shape>_<aa|noaa>.png` に出力するのでモード比較しやすい。
  - 例：`python render_catalog.py --shape square --no-aa` → `hyg_square_noaa.png`（実機相当）。
- **見え方の指針**（実機検証で確定予定）：低解像度 LCD では **四角ドット＋AA 無し＋等倍**が最も
  くっきり（丸は小径だと Pillow で「＋」に欠ける／AA は小文字を眠くする）。星サイズは等級別に
  1等=3×3 / 2等=2×2 / 3等以下=1ドット。`_4x` は NEAREST 拡大なので等倍ピクセルをそのまま確認できる。
- **知見**：等級 6.5 の全星（地平線上 ~4,200）は 320×170 には密すぎる。LCD 実表示は
  **mag ≤ 4.0〜4.5**（地平線上 ~250）が読みやすい。等級でサイズ/明るさを付ける本実装で調整する。
- 検証（2026-07-07・札幌 21:30）：北斗七星・夏の大三角・夏の天の川の帯・Antares/Spica/Arcturus
  等の位置が天文的に妥当であることを確認。

## 共通コア

変換・ロードは [`shared/star_catalog/`](../../../shared/star_catalog/) に集約：

- `transform.py`：ユリウス日 → 恒星時 → 地平座標(Alt/Az) → 円形全天図ピクセル
- `catalog.py`：`stars.bin` / メタ / 固有名のローダ（`StarCatalog`・`by_name`/`by_hip`）
