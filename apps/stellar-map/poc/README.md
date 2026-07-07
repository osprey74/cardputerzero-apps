# App 16 星座盤 ― PoC（投影パイプライン先行検証）

実機・ネットワーク・天体暦ダウンロード無しで、**星座盤の投影パイプライン**を検証する PoC。
指定した日時・観測地点の可視恒星＋星座線を **320×170**（CardputerZero LCD 相当）に投影し PNG 出力する。

## なぜ Skyfield 無しか

恒星と星座線だけなら、惑星・月用の JPL 天体暦（Skyfield）は不要で、古典的な
**「ユリウス日 → グリニッジ恒星時 → 地方恒星時 → 地平座標(Alt/Az)」** 変換で自己完結できる。
これにより PoC はネット・暦ファイル無しで即実行・検証可能。惑星・月・高精度化は次段で
Skyfield に差し替える想定で、変換部（`radec_to_altaz` 等）を独立関数にしてある。

## 投影

HANDOFF App01「Sky Plot 天球図」の極座標変換を流用：

- 左 170×170：円形全天図（中心=天頂 alt90° / 外周=地平線 alt0° / 北=上）
- 右 150×170：情報パネル（日時・観測地・LST・地平線上の星数）
- 地平線下（alt<0）の星・線は描かない
- `--mirror-ew`：天頂を見上げる向き（planisphere）に東西反転

## 実行

```bash
python star_poc.py                                   # 既定: 札幌 2026-07-07 21:30 JST
python star_poc.py --lat 35.68 --lon 139.77 --dt "2026-12-01T22:00"   # 東京・冬
python star_poc.py --mirror-ew                       # 見上げる向き
```

依存: `Pillow` のみ（`numpy` は不要）。出力は `out/skychart.png` と拡大版 `out/skychart_4x.png`。

## 検証結果（2026-07-07）

札幌 2026-07-07 21:30 JST で天文的に妥当な描画を確認：

- 北斗七星（おおぐま座）が北西・高い位置
- 夏の大三角（Vega/Deneb/Altair）とはくちょう座「北十字」が東に上昇
- カシオペヤ座が北・低空
- 冬のオリオン座・シリウスは地平線下で非表示（正しく除外）
- 地平線上 23/35 星

## データについて（ライセンス）

PoC は依存とライセンス束縛を避けるため、明るい恒星の最小サンプル（J2000 の RA/Dec は事実データ）を内蔵。
本実装では以下を取り込む（HANDOFF §3 App16 参照）：

- 恒星：**HYG Database（CC BY-SA 4.0）**
- 深宇宙天体：**OpenNGC（CC BY-SA 4.0）**
- 星座線：**Stellarium 現代星座線の線分定義（MIT）**
- 惑星・月：**Skyfield（MIT）＋ JPL DE 暦（実質 PD）**

CC BY-SA データは再配布時にライセンス維持＋クレジット必須。元アプリ
[wisnc/stellar-map](https://github.com/wisnc/stellar-map) は**ライセンス無し＝全権留保のためコード非流用**、一次データから再実装する。

## 次段 TODO

- [ ] HYG / OpenNGC の実データ取り込み（前処理ツールを自作）
- [ ] Skyfield で惑星・月・月相を追加
- [ ] czdev/LVGL 描画への接続（バッファ一括転送）
- [ ] 方位アライン：CoreS3 の地磁気センサ値を USB CDC 経由で取り込み（`shared/cores3_bridge/`）
