# rangetest_analyze — Meshtastic レンジテスト到達距離解析

App 02 `lora-mesh-node` の補助ツール。**固定局(C6L)＝送信 / 移動局(PaperMono)＝受信**の
レンジテストで、受信ログ(`rangetest.csv`)と Garmin 等の GPX トラックを**時刻で突合**し、
距離ごとの RSSI/SNR・パケット到達率を可視化する。両機とも GPS 非搭載のため位置は GPX 側から与える。

## セットアップ

```bash
pip install -r requirements.txt
```

## 前提データ

| 入力 | 取得元 | 要点 |
| --- | --- | --- |
| `rangetest.csv` | 移動局(PaperMono) Range Test **receiver** | `time,sender,rx_snr,num,rx_rssi,distance,hop_limit,payload`。連番は payload の整数から抽出 |
| GPX トラック | Garmin GPSMAP 67i 等 | 記録間隔は**時間ベース1秒**推奨。時刻は UTC(Z) |
| 固定局座標 | 67i でウェイポイント等 | `lat,lon`(10進) |

> ⚠️ **時計合わせが命**: receiver の RTC が UTC に同期していないと突合がズレる。出発前に
> Meshtastic アプリ等で時刻同期を。ズレが既知なら `--rx-clock-offset <秒>` で補正。実行時に
> 突合時刻差の中央値を診断表示するので、大きければ同期を疑う。

## 使い方

```bash
python rangetest_analyze.py \
    --gpx track.gpx \
    --csv rangetest.csv \
    --fixed 43.06417,141.34694 \
    --out-dir ./rangetest_out
```

主なオプション:

- `--rx-clock-offset <秒>` … 受信機時計の補正(RX 時刻に加算)
- `--max-dt <秒>` … GPX 突合の許容時刻差(既定 30s)。超過受信点は信号グラフ/マップから除外(到達率には残す)
- `--bin-width <m>` … 到達率の距離ビン幅(既定 100m)
- `--interval <秒>` … 送信間隔。指定すると区間外(先頭前・末尾後)の欠落も外挿して到達率に含める
- `--seq-min / --seq-max` … 連番範囲を明示

## 出力(`out-dir`)

- `enriched.csv` … 連番ごとの received/距離/RSSI/SNR/GPX時刻差
- `dist_vs_rssi_snr.png` … 距離 vs RSSI・SNR
- `delivery_vs_distance.png` … 距離ビンごとの到達率(欠落連番は時刻線形補間で位置推定)
- `track_rssi_map.png` … 受信点を RSSI 色分けした軌跡＋固定局

標準出力に「最遠受信距離」「到達率50%維持距離」等のサマリを表示。

## 到達率の考え方

「最遠で1発届いた」よりも**距離ごとの到達率(連番の欠落から算出)**が実運用の指標。欠落連番は
前後受信の時刻を線形補間して発信時刻を推定し、GPX 最近傍で位置化してビン集計する。
`--interval` を与えると区間外の欠落も外挿対象になる。

## 備考

- GPSMAP 67i の inReach(Iridium 衛星)は本解析と無関係。67i は純粋に GPS トラック源。
- 送信する全機は日本国内 920MHz 帯の技適が必要(C6L=技適 211-250603 確認済 / PaperMono 側は要確認)。
