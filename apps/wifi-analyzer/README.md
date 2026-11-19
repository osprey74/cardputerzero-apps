# App07 Wi-Fi Analyzer（`wifi-analyzer`）

CardputerZero の内蔵 Wi-Fi で周辺のアクセスポイント（AP）を調べるアプリです。
画面は 320×170 のフレームバッファへ直接描きます（Python・Pillow＋numpy）。

受信するのは AP が出しているビーコン（どの端末の Wi-Fi 一覧にも出る情報）だけです。
他人のネットワークへの接続・通信内容の取得・電波の送信は行いません。

## 画面

| 画面 | 内容 |
|---|---|
| 1 一覧 | 信号の強さ（%）・チャンネル・SSID・暗号方式。`*` は接続中の AP。OPEN／WEP は赤で表示 |
| 2 チャンネル | 2.4GHz 帯の 1〜14ch に、各 AP の占有帯域（20MHz ≒ ±2ch）を台形で重ねて表示。下段の数字は ch ごとの AP 数 |
| 3 グラフ | 選んだ AP の信号の推移（直近 10 分）。接続中の AP は `/proc/net/wireless` の dBm を 1 秒ごと、それ以外は nmcli の相対値（%）をスキャンごとに描く |

## キー操作

| キー | 動作 |
|---|---|
| Z／C（←→）・Tab・1〜3 | 画面の切り替え |
| F／X（↑↓） | AP の選択（どの画面でも共通）。カーソルは Fn なしの単独押しでも動く |
| Enter | 一覧からグラフへ |
| Esc | 一覧へ戻る（長押しはランチャーが終了させる） |
| R | すぐに再スキャン |
| O | 並べ替え（強い順・ch 順・名前順） |
| L | CSV 記録の開始・停止（`~/wifi_logs/wifi_<日時>.csv`） |
| S | 画面を PNG で保存（`~/wifi_shots/`） |
| Q | 終了 |

## 仕組み

- 周辺 AP は `nmcli -t dev wifi list --rescan yes` を約 10 秒ごとに実行して取得します（`pi` ユーザーのまま再スキャンでき、`iw` や root は不要）。再スキャンが間隔制限で断られたときは、NetworkManager が持っている最新の結果を使います。
- nmcli の信号値は 0〜100 の相対値で、dBm は出ません。dBm を出せるのは接続中の AP だけです。
- 60 秒以上見えなくなった AP は一覧から外します。

## 動作確認（PC・実機の SSH）

```bash
# 疑似データで画面を確認（PC でも動く）
python3 src/wifi_analyzer.py --demo --headless --script "4 shot /tmp/list.png; 4.5 2; 5 shot /tmp/chan.png; 6 quit"
# テスト
python3 -m unittest discover -s tests
```

ランチャーを通さずに LCD へ描くと、ランチャーの表示とキー処理が重なります。実機での確認はランチャーから起動するか、`--headless` を使ってください。

## パッケージ

```bash
bash scripts/pack_deb.sh apps/wifi-analyzer       # 実機上で実行（dpkg-deb が必要）
apt-get -s install ./apps/wifi-analyzer/dist-cz/*.deb   # 試算で他のパッケージが変わらないことを確認
sudo apt install ./apps/wifi-analyzer/dist-cz/*.deb
```

依存は工場出荷イメージに入っている `python3`・`python3-pil`・`python3-numpy`・`network-manager` だけです。
画面とキー入力の共通部品 `shared/fb_ui/` を同梱します。
