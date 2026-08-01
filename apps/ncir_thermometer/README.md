# App 15 非接触温度計 (`ncir-thermometer`)

CoreS3 + **MLX90614（NCIR 非接触温度センサ）** で、発熱部品のデバッグを補助する
温度モニタ PoC。CoreS3 firmware が USB CDC で送る温度テレメトリを PC 側の
Python が受け、**閾値ステータス（NORMAL / WARN / ALERT）を色分け**しつつ
セッションの Min/Max・平均・サンプル数を Rich TUI で表示する。設計の一次資料は
[`HANDOFF.md`](HANDOFF.md)（本アプリ）／[`../../HANDOFF_cardputerzero.md`](../../HANDOFF_cardputerzero.md) §App 15。

> ⚠️ **本ツールは電子工作・IoT デバッグ用途です。体温計・発熱スクリーニング等の医療用途には使えません。**

## アーキテクチャ（CoreS3 firmware ＋ Python PoC）

温度取得（MLX90614 の SMBus 読取・`raw × 0.02 − 273.15` で ℃ 変換）は **CoreS3 firmware 側で実装済み**。
本アプリは [`shared/cores3_bridge`](../../shared/cores3_bridge/) 経由で `Frame` を受け、`Frame.ncir`
（`Temp(t_obj, t_amb)`）を閾値判定・統計・TUI 表示するだけの薄い PoC。

```
CoreS3 (Arduino/M5Unified)                     PC (開発機)
  MLX90614 0x5A ── SMBus ──┐
                           ▼
  {"...","ncir":{"t_obj":36.5,"t_amb":24.1}}
                           │  USB CDC (COM5 / /dev/ttyACM0)
                           ▼
        shared/cores3_bridge (CoreS3Reader → Frame)
                           │  Frame.ncir = Temp(t_obj, t_amb)
                           ▼
        thermometer_poc.py
          ├─ classify()  NORMAL / WARN / ALERT（色分け）
          ├─ Stats       Min/Max・平均・サンプル数（r キーでリセット）
          └─ Rich TUI    1Hz 以上で更新 ／ 統計行を stderr へ
```

## 使い方

依存：`rich` / `pyserial`（`pyserial` は `cores3_bridge` が既に要求）。

```bash
pip install rich pyserial
```

### 実機（CoreS3 を USB 接続）

```bash
# リポジトリ直下から（-m 実行）
python -m apps.ncir_thermometer.thermometer_poc --port COM5

# または apps/ncir_thermometer/ 内から（スクリプト直実行）
python thermometer_poc.py --port COM5
```

- `r` キー … Min/Max をリセット
- `Ctrl+C` … 終了時にセッションのサマリを表示

### モック（CoreS3 なしで PC 単体確認）

```bash
python -m apps.ncir_thermometer.thermometer_poc \
    --mock-file shared/cores3_bridge/tests/sample_frames.jsonl
```

## CLI オプション

| オプション | 既定 | 説明 |
|---|---|---|
| `--port` | `default_port()`（Win=COM5 / 他=/dev/ttyACM0） | シリアルポート |
| `--warn-threshold` | `80.0` | WARN 閾値 ℃（`t_obj ≥` で黄） |
| `--alert-threshold` | `100.0` | ALERT 閾値 ℃（`t_obj ≥` で赤） |
| `--report-interval` | `5.0` | 統計行を stderr へ出す間隔（秒） |
| `--mock-file` | — | jsonl をループ再生（PC 単独テスト） |
| `--max-frames` | `0`（無制限） | 指定フレーム数で終了（テスト用） |

## 動作確認（実機 COM5・2026-08-01）

| 対象 | 実測 | ステータス |
|---|---|---|
| 常温 | obj avg=35.8 / min=29.8 / **max=40.7℃**（150 samples） | NORMAL（緑） |
| ハンダゴテ | obj avg=64.6 / min=29.5 / **max=106.2℃**（354 samples） | ALERT（赤）発火 |

> ハンダゴテ計測はセンサー保護のため 100℃ 超確認で停止。MLX90614 の測定上限は
> **-70〜+380℃**。至近距離は非接触でも破損リスクがあるため**コテ先から 5cm 以上**離すこと。

## テスト

```bash
# pytest
python -m pytest apps/ncir_thermometer/tests
# pytest 無し簡易ランナー
python apps/ncir_thermometer/tests/test_thermometer_poc.py
```

閾値判定（境界値・None）と統計（Min/Max・reset・片側欠測・空平均）を 6 ケースで検証。

## 環境上の注意（Windows）

- **`-m` 実行はリポジトリ直下から**。アプリフォルダ内では `apps` が見つからないため、
  その場所からは `python thermometer_poc.py` を使う。
- **実機ターミナルが PlatformIO 仮想環境になっていると `rich` が無い**ことがある。
  その場合は現在の Python に `pip install rich`（`pyserial` も無ければ追加）。
- 既定コンソール（cp932）対策として stdout/stderr を UTF-8 に強制し、Rich の
  レガシー Windows 描画を無効化している（`°` や `—` の文字化け・例外を回避）。

## 関連

- [`HANDOFF.md`](HANDOFF.md) … 本 PoC の一次設計書
- [`shared/cores3_bridge`](../../shared/cores3_bridge/) … USB CDC 受信・パーサ（共通）
- note 12-1.10「CoreS3 で非接触温度ガジェットを作る（NCIR MLX90614）」（執筆連携）
