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
- 送信する全機は日本国内 920MHz 帯の技適が必要(C6L=技適 211-250603 / PaperMono=技適 211-260514、いずれも 2026-11-17 に認証条件まで照合済)。
- 技適は番号だけでなく**認証条件(周波数・帯域幅・出力・送信時間)の範囲内**で使う必要がある。Cap LoRa-1262(211-251216)は 922.0〜923.4MHz・125kHz/5mW・1 回 0.4 秒未満で、Meshtastic 既定の LongFast では送信できない(HANDOFF §3 App02)。CardputerZero をレンジテストに使う場合は**受信側**とする。C6L(211-250603)の LoRa 認証条件も Cap と同一(5mW・125/500kHz・1 回 0.4 秒未満)で、**従来の JP/13dBm/LongFast 設定は認証条件の外**。C6L は現在 Nostos の `firmware/c6l-beacon`(923.0MHz・125kHz・+6dBm・LBT)で稼働しており認証条件内(2026-11-17 確認)。本ツールは Meshtastic の Range Test ログを前提にしているため、今後のレンジテストはビーコン受信ログを入力とする形に改める必要がある。PaperMono の LoRa 認証は 500kHz・7mW のみのため、受信側として使う。

## sx1262_rx_probe — Cap LoRa-1262 受信専用プローブ(CardputerZero 実機用)

[`sx1262_rx_probe.py`](sx1262_rx_probe.py) は、CardputerZero に Cap LoRa-1262 を装着した状態で
SX1262 の配線・初期化を確認し、C6L の Nostos ビーコンを受信して RSSI・SNR・CRC を表示する。
**送信コマンドは一切発行しない受信専用**のスクリプト。

```bash
# 実機へ転送して実行(工場出荷イメージの python3 / spidev / gpiod / i2c-tools だけで動く・sudo 不要)
scp sx1262_rx_probe.py pi@cardputerzero.local:
ssh pi@cardputerzero.local 'LISTEN=600 python3 sx1262_rx_probe.py'
```

- 標準の LoRa / GPS アプリを終了してから実行する(SPI・UART・5V 出力を取り合うため)。
- 起動時に EXT 5V 出力を ON にし、終了時に元の状態へ戻す。
- 受信設定は 923.000MHz・BW125kHz・SF9・CR4/5・同期語 0x3A(Nostos ビーコン)に固定。
- 受信フレームの位置(緯度・経度)は表示しない。
- 配線と初期化手順の根拠は HANDOFF §9.1「Cap A: Cap LoRa-1262」。2026-11-17 に 7 通を欠けなく受信して確認済み。
- 上記の `requirements.txt` は `rangetest_analyze.py` 用で、本スクリプトには不要。

## lora_airtime — 送信時間と Meshtastic プリセットの計算

[`lora_airtime.py`](lora_airtime.py) は、LoRa 1 パケットの送信時間（Time on Air）と、Meshtastic の各プリセットが
日本（JP）リージョンで既定で使う周波数を計算する。標準ライブラリだけで動き、電波は出さない。

```bash
python3 lora_airtime.py              # プリセット一覧と送信時間の表
python3 lora_airtime.py --selftest   # HANDOFF §3 App02 の表（44 点）と照合
python3 lora_airtime.py --bw 125 --sf 9 --cr 5 --len 16 --preamble 8   # 1 点だけ計算
```

- 送信時間の式は Semtech SX1261/2 データシート 6.1.4。RadioLib の `PhysicalLayer::calculateTimeOnAir()` と同じ式であることをソースで確認した(2026-11-17)。
- プリセット・周波数の決め方・パケット構成は meshtastic/firmware の master `6d41e279`(2026-08-20)で確認した(最新リリースは v2.7.26、2026-06-24 公開)。**プリセットは版で変わり得る**ので、使う前に版を確かめる。
  - プリセット → 帯域幅・SF・CR: `src/mesh/MeshRadio.h` の `modemPresetToParams()`
  - JP リージョン: `src/mesh/RadioInterface.cpp` の `RDEF(JP, 920.5f, 923.5f, 100, 0, 13, ...)`(920.5〜923.5MHz・出力上限 13dBm)
  - 周波数: 同 `applyModemConfig()`。スロット数＝`floor(3.0MHz / 帯域幅)`、スロット＝`djb2(チャネル名) % スロット数`、中心＝`920.5 + 帯域幅/2 + スロット × 帯域幅`
  - パケット: `src/mesh/RadioLibInterface.h` の `getPacketConfig()`(プリアンブル 16・明示ヘッダ・CRC あり・シンボル時間 16ms 以上で LDRO)。ヘッダは `PacketHeader` の 16 バイト
  - 送信前の確認: `SX126xInterface::isChannelActive()` は `scanChannel()`(LoRa 信号の検出＝CAD)。受信電力のしきい値による判定ではない
- 検算: HANDOFF §3 App02 の表 44 点がすべて一致。Nostos ビーコン(125kHz・SF9・CR4/5・16 バイト・プリアンブル 8)は 164.9ms で、Nostos 側の記載(約 165ms)と一致。LongFast の JP 既定は 923.375MHz で、Nostos `docs/COMPLIANCE.md` の記載と一致。
- わかったこと(確認した版・既定スロットの場合。計算値であり送信の可否を保証しない):
  - **認証の「922.0〜923.4MHz」は中心周波数の範囲**。試験成績書の Channel List は 922.0〜923.4MHz・200kHz 刻みの 8 波で、125kHz 幅も 500kHz 幅も同じ中心(試験は 922.0／922.8／923.4MHz)。実測の占有範囲は中心の外へ広がる(500kHz 幅・923.4MHz で 923.146〜923.654MHz)。したがって適否は「占有上端が 923.4MHz を超えるか」ではなく「中心が 8 波に一致するか」で見る(Cap LoRa-1262・C6L・PaperMono の 3 機種とも同じ Channel List。2026-11-17 に PDF で確認)
  - 既定の LongFast は 250kHz・SF11・CR4/5、中心 923.375MHz。帯域幅が試験対象外で、中心も 8 波に一致しない。0.4 秒未満に収まるのはヘッダ込み 22 バイト(本文 6 バイト)まで
  - 125kHz 幅のプリセットは LongMod(SF11・CR4/8)と LongSlow(SF12・CR4/8)だけで、どちらも最短のパケットで 0.4 秒を超える。既定の中心(922.1875MHz／920.8125MHz)も 8 波に一致しない
  - 500kHz 幅のプリセットは ShortTurbo(SF7・CR4/5)と LongTurbo(SF11・CR4/8)。既定スロットはどちらも中心 923.25MHz で、8 波に一致しない。ShortTurbo は最大長 255 バイトでも約 102ms なので、**周波数を 8 波のどれかに明示指定し、出力を 1.5mW 以下に下げれば、周波数・帯域幅・送信時間の 3 点は条件に入る**(キャリアセンスは下記のとおり未確認)
  - つまり確認した版では、既定の周波数のまま 8 波に一致するプリセットは無い
  - JP リージョンの出力上限は 13dBm(約 20mW)で、Cap の認証値(125kHz で 5mW・500kHz で 1.5mW)より大きい。出力は利用者が下げる必要がある
- 未確認: CAD による送信前確認が認証条件のキャリアセンスに当たるかどうか(総司判断で未確認のまま据え置き・2026-11-17)。
