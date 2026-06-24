# cores3_bridge

CoreS3 入力フロントエンド（`firmware/cores3-frontend/`）が USB CDC で送る JSON
テレメトリを受信し、機種非依存のデータモデルに変換する Python ライブラリ。
HANDOFF §1.6.1 の「CoreS3 経由（第一推奨）」経路の受信側にあたる。

開発機（Windows / COM5）でも CardputerZero 実機（Linux / `/dev/ttyACM*`）でも
同じコードで動く。Chain Encoder は **UID 解決済みの `role`/`uid` で個体を束ねる**
ため、ケーブル接続順を入れ替えても同じ個体を指せる。

## 構成

| ファイル | 役割 | 依存 |
|---|---|---|
| `models.py` | `Battery`/`Power`/`Temp`/`Encoder`/`Frame`/`LogLine` データクラス | 標準ライブラリのみ |
| `parse.py` | 1 行 → `Frame`/`LogLine` 変換・`nan`/`inf` の null 化 | 標準ライブラリのみ |
| `reader.py` | `CoreS3Reader`（シリアル読出し） | `pyserial` |
| `cli.py` | サマリ表示 / `--json` 中継 / `--watch` ライブ監視 | `pyserial` |
| `tests/` | パーサ・モデルの単体テスト（実機・pyserial 不要） | （任意で pytest） |

`models.py` と `parse.py` はシリアル非依存なので、実機が無くても単体テスト可能。

## 使い方

```python
from shared.cores3_bridge import CoreS3Reader

with CoreS3Reader() as rd:            # 既定ポート: Windows=COM5 / 他=/dev/ttyACM0
    for f in rd.frames():
        red  = f.encoder(role="R")    # 配線順によらず「赤」を取得（UID 解決）
        blue = f.encoder(role="B")
        if red and red.delta:
            print("RED rotated", red.delta, "→ total", red.cnt)
        if f.ina:
            print("V", f.ina.v, "I", f.ina.i, "P", f.ina.p)
```

CLI:

```sh
python -m shared.cores3_bridge.cli            # 1 行サマリ
python -m shared.cores3_bridge.cli --json     # 正規化 JSON を中継（nan→null 済み）
python -m shared.cores3_bridge.cli --watch    # 1 画面ライブ更新
python -m shared.cores3_bridge.cli --port /dev/ttyACM0
```

## 受信する JSON

```json
{"bat":{"pct":100,"chg":0,"v":4.12},
 "ina":{"v":0.0,"i":0.0,"p":0.0},
 "ncir":{"t_obj":28.5,"t_amb":31.4},
 "enc":[{"id":1,"role":"B","uid":"78001C00","cnt":-24,"delta":0,"btn":0},
        {"id":2,"role":"R","uid":"4E001B00","cnt":39,"delta":1,"btn":0}]}
```

- `id` … チェーン上の物理位置（1 始まり・**配線順で変わる**）
- `role` … UID 解決した役割（`R`/`B`/`?`・**配線順非依存**）
- `uid` … STM32 固有 4 バイト UID（個体固定）。確定値: 赤=`4E001B00` / 青=`78001C00`
- 別途 `{"log":"..."}` 行（`i2c_scan`/`ina226_id`/`chain_enum`/`chain_uid`）も流れる。
  `stream(include_logs=True)` で `LogLine` として受け取れる。

> ⚠️ センサ読取失敗時、ファームは `nan` を出力し JSON として不正になるため、
> `parse.py` が値位置の `nan`/`inf` を `null`（→ `None`）に変換してから読む。

## テスト

```sh
python shared/cores3_bridge/tests/test_parse.py     # pytest 無しでも走る簡易ランナー
# または
python -m pytest shared/cores3_bridge/tests
```

## 依存

- `pyserial`（`reader.py`/`cli.py` のみ。パース層・テストには不要）

## 関連

- 送信側: `firmware/cores3-frontend/src/main.cpp`
- 仕様: HANDOFF §1.6.1（CoreS3 入力フロントエンド）
