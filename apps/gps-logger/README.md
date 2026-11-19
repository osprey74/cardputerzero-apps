# App01 GPS Logger（`gps-logger`）

CardputerZero で走行・サイクリングのルートを GPX 1.1 に記録するアプリです。
GPS は Cap LoRa-1262 の内蔵 GPS か、Grove ポートに挿した Unit GPS v1.1 を使います（受信のみ）。
画面は 320×170 のフレームバッファへ直接描きます（Python・Pillow＋numpy）。

## 画面

| 画面 | 内容 |
|---|---|
| 1 メーター | 速度（大）・標高・進行方向と、距離・記録時間・平均速度・最高速度・獲得標高・記録点数。下段に測位状態（3D／2D／未測位）・使用衛星数／見えている衛星数・HDOP・GPS の種類。測位前は「衛星を探しています」の待機画面（受信中の衛星の SNR を棒グラフで表示） |
| 2 天球図 | 左に衛星の位置（中心＝天頂・外周＝地平線・上が北）、右に衛星の一覧（SNR の棒・仰角）。色は GPS 緑・みちびき 赤・GLONASS 青・Galileo 黄・BeiDou 紫。塗りつぶし＝測位に使用中、丸の大きさ＝SNR |
| 3 軌跡 | 記録中のルートの形（北が上・縮尺付き）。緑の四角が出発点、赤丸が現在地 |
| 4 詳細 | 緯度・経度・標高・速度と方向・時刻・測位の詳細・GPS の種類・記録中のファイル名・電池残量 |

## キー操作

カーソルは Fn なしの F／X／C／Z（↑↓→←）でも動きます。

| キー | 動作 |
|---|---|
| Enter | 記録開始 → 一時停止 → 再開 |
| E を 2 回 | 記録を終了して保存（3 秒以内に 2 回） |
| Z／C・Tab・1〜4 | 画面の切り替え |
| F／X | 天球図で衛星を選ぶ（選んだ衛星に白い輪） |
| G | GPS の切り替え（auto → grove → cap。記録していないときだけ。選んだ値は保存される） |
| B | 画面の明るさ（明 → 暗 → 消灯）。消灯中はどのキーでも点灯 |
| Esc | メーターへ戻る（長押しはランチャーが終了させる。記録中なら保存してから終わる） |
| S | 画面を PNG で保存（`~/gps_shots/`） |
| Q | 終了（記録中は 2 回押し。保存してから終わる） |

## 記録

- 保存先は `~/gps_logs/track_<日時>.gpx`。GPX 1.1 で、各点に標高・時刻（GNSS の UTC）・2D／3D・衛星数・HDOP を書きます。速度は GPX 1.1 の標準要素に無いため書きません（Rindo などの取り込み側で計算できます）。
- 1 点ずつ追記し、30 秒ごとにディスクへ書き込みます。電池切れや強制終了で閉じタグが無いまま残ったファイルは、次の起動時に自動で閉じます。
- 一時停止すると区間（`<trkseg>`）を閉じ、再開で新しい区間を始めます。停止中の移動は距離に入れません。
- 統計: 止まっているときの位置のふらつき（時速 1.5km 未満かつ 10m 以内）は距離に入れません。最高速度と獲得標高は 3D 測位・HDOP 3 以下の点だけで数えます（標高は 3m の幅を持たせて上下を数えます）。

## GPS の選び方

設定は `~/.config/cardputerzero/gps_logger.json` の `"gnss"`（G キーで変更できます）。

| 値 | 動作 |
|---|---|
| `auto`（既定） | Cap の 5V を入れて 8 秒待ち、NMEA が来なければ Grove の 5V に切り替える |
| `grove` | Grove ポートの GPS ユニットを使う |
| `cap` | Cap LoRa-1262 の GPS を使う |

どちらも `/dev/serial0`（115200bps）を使うため、星座盤や標準の GPS アプリとは同時に使えません。
終了時は 5V 出力を起動前の状態に戻します。

## 動作確認

```bash
# 架空の周回データで画面を確認（PC でも動く・GPS の電源は入れない）
python3 src/gps_logger.py --demo --headless --script "4 enter; 30 shot /tmp/dash.png; 30.5 2; 31 shot /tmp/sky.png; 32 quit"
python3 -m unittest discover -s tests                 # 記録部のテスト
python3 ../../shared/gnss_at6668/tests/test_nmea.py   # NMEA（GSV・GSA を含む）のテスト
```

## パッケージ

```bash
bash scripts/pack_deb.sh apps/gps-logger           # 実機上で実行（dpkg-deb が必要）
apt-get -s install ./apps/gps-logger/dist-cz/*.deb # 試算で他のパッケージが変わらないことを確認
sudo apt install ./apps/gps-logger/dist-cz/*.deb
```

依存は工場出荷イメージに入っている `python3`・`python3-pil`・`python3-numpy` だけです。
`shared/fb_ui/` と `shared/gnss_at6668/` を同梱します。

> 記録した GPX には実際の位置が入ります。公開リポジトリやスクリーンショットに載せないでください。
