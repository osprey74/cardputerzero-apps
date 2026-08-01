# HANDOFF: App 15 ncir-thermometer PoC

**作成日**：2026-08-01
**執筆記事連携**：note 12-1.10「CoreS3 で非接触温度ガジェットを作る（NCIR MLX90614）」（2026-09-19 公開予定）
**目的**：CoreS3 firmware 側で既に取得済みの MLX90614 温度データ（t_obj / t_amb）を Python 側で受け、**発熱部品デバッグの実用ツール**として最小限の PoC を実装する

---

## 1. Context（現在地）

### 既に動いているもの（実装済み・活用対象）

- **`firmware/cores3-frontend/src/main.cpp`**：MLX90614（I2C アドレス 0x5A）を SMBus で読み取り、`raw × 0.02 − 273.15` で ℃ 変換 → JSON 1 行を USB CDC で送信済み
  - 送信フォーマット例：`{"ncir": {"t_obj": 36.5, "t_amb": 24.1}}`
  - METER ページに「NCIR MLX90614」枠で obj / amb 横並び表示済み
  - INFO ページの `room` は amb を再利用済み
- **`shared/cores3_bridge/`**（Python 側受信）
  - `models.py`：`Temp(t_obj: float, t_amb: float)` データクラス
  - `parse.py`：JSON 行 → Temp オブジェクト変換
  - `cli.py`：Rich TUI ベースの受信 CLI
  - `sample_frames.jsonl`：実測サンプル値
    - `t_obj=28.53, t_amb=31.37`
    - `t_obj=36.50, t_amb=24.10`
  - `tests/test_parse.py`：単体テスト
- **物理経路**：CoreS3 Port A → Hub Unit U006 で INA226 と同居（PaHUB 不要・アドレス衝突なし）

### 未実装（本 HANDOFF の対象）

- **`apps/ncir-thermometer/` ディレクトリ**：空すら未作成 ← **本ディレクトリ作成中**
- **Python 側 PoC ワンファイル**：閾値監視 + Min/Max 保持
- **App 15 として `app.yaml` / `app-builder.json`**：他アプリと整合させる必要あり

---

## 2. Goal（このタスクの完了条件）

以下 3 点をすべて満たしたら PoC 完成：

1. **`apps/ncir_thermometer/thermometer_poc.py`** が動作（実装後 ~190 行：閾値判定＋統計の**コアは ~40 行**〈`classify()` + `Stats`〉で、残りは Rich TUI 描画・`r` キーリセット・シリアル自動再接続・Windows UTF-8 対策）
2. `cores3_bridge` の `CoreS3Reader` から `Frame` をリアルタイム受信し、`Frame.ncir`（`Temp`）を Rich TUI で表示
3. **常温掌 → ハンダゴテ**を測る実測フローが完走し、閾値ステータス遷移が視認できる

### 完成の判定基準

- 常温掌に向けた瞬間 `t_obj ≈ 33℃`（緑・通常）
- ハンダゴテのコテ先に向けた瞬間 `t_obj ≥ 100℃`（赤・アラート）
- Min/Max が正しく保持され、リセットコマンドで初期化される

---

## 3. Interface / Contract

### 入力

**受信元**：`shared/cores3_bridge` の `CoreS3Reader` から `Frame` を継続受信し、
`Frame.ncir`（`Optional[Temp]`）を取り出す。

```python
# 実 API に合わせた呼び出しパターン（cores3_bridge/reader.py）
from shared.cores3_bridge import CoreS3Reader, default_port

with CoreS3Reader(port=default_port()) as rd:   # 既定: Windows=COM5 / 他=/dev/ttyACM0
    for frame in rd.frames():                   # Frame のみ yield（LogLine は読み飛ばし）
        temp = frame.ncir                        # 属性は .ncir（.temp ではない）
        if temp is None or temp.t_obj is None:   # ncir 欠落・nan(None化) はスキップ
            continue
        # PoC のロジックへ（temp.t_obj / temp.t_amb）
        ...
```

> ⚠️ **API 上の注意（実装時に厳守）**
>
> - フレーム属性は `Frame.ncir`（`Temp` 型）。`frame.temp` は存在しない。
> - `t_obj`/`t_amb` は `Optional[float]`。firmware の `nan` はパーサで `None` 化されるため、閾値判定・統計へ入れる前に `None` を弾く。
> - `parse_line` は **"enc" か "ina" を含む行のみ** `Frame` 化する。実 firmware は bat/ina/ncir/enc を 1 行同梱で送るため問題ないが、モック用に手書きする単独行 `{"ncir":{...}}` は `Frame` にならない（`sample_frames.jsonl` の同梱形式を使うこと）。

### CLI オプション

```
python -m apps.ncir_thermometer.thermometer_poc \
    --port COM5                     # シリアルポート（既定：default_port() → Win=COM5 / 他=/dev/ttyACM0）
    --warn-threshold 80.0           # 警告閾値 ℃（既定：80.0）
    --alert-threshold 100.0         # アラート閾値 ℃（既定：100.0）
    --report-interval 5.0           # 統計表示間隔・秒（既定：5.0）
    --mock-file shared/cores3_bridge/tests/sample_frames.jsonl  # モック入力（テスト用）
```

### 出力

**Rich TUI で常時表示**：

```
┌─ NCIR Thermometer PoC ─────────────────────────┐
│  t_obj  36.5 °C   [WARN  <  80.0]              │
│  t_amb  24.1 °C                                │
│                                                │
│  Session Min / Max                             │
│    t_obj  min 25.3 °C   max 372.4 °C           │
│    t_amb  min 22.5 °C   max 28.1 °C            │
│                                                │
│  Status: NORMAL / WARN / ALERT                 │
│  Samples: 1,247   Interval: 5.0 s              │
└────────────────────────────────────────────────┘
```

**5 秒ごとに統計行を追加**（stderr 経由）：
```
[2026-09-15 20:16:23] avg=36.5 min=25.3 max=372.4 samples=1247
```

---

## 4. Architecture

### 単一ファイル構成

```
apps/ncir_thermometer/       ← ★ ディレクトリはアンダースコア（`python -m` の import 名と一致させる）
├── HANDOFF.md              ← 本ファイル
├── __init__.py             ← パッケージ化（-m 実行用）
├── README.md               ← 実装後に作成（他アプリと揃える）
├── app.yaml                ← M5Stack エコシステム標準メタ
├── app-builder.json        ← czdev 統合用
├── thermometer_poc.py      ← ★ 本 PoC のメインファイル（実装後 ~190 行・閾値コアは ~40 行）
└── tests/
    └── test_thermometer_poc.py  ← 閾値判定ロジックの単体テスト
```

### 依存

- `shared/cores3_bridge`（既存・そのまま使う）
- `rich` >= 13.x（TUI）
- `pyserial` >= 3.5（cores3_bridge が既に依存）

### データフロー

```
CoreS3 (Arduino/M5Unified)
    │
    │  USB CDC
    │  {"ncir": {"t_obj": 36.5, "t_amb": 24.1}}
    ▼
shared/cores3_bridge (parse.py)
    │
    │  Temp(t_obj=36.5, t_amb=24.1)
    ▼
apps/ncir-thermometer/thermometer_poc.py
    │
    ├─ 閾値判定（NORMAL / WARN / ALERT）
    ├─ Min/Max 保持（セッション単位）
    ├─ 統計計算（avg / count）
    └─ Rich TUI 更新
```

---

## 5. Must-have Features

1. **リアルタイム表示**：t_obj / t_amb を常時表示（Rich Live で 1 Hz 以上のリフレッシュ）
2. **閾値ステータス**：
   - `t_obj < warn_threshold` → NORMAL（緑）
   - `warn_threshold ≤ t_obj < alert_threshold` → WARN（黄）
   - `t_obj ≥ alert_threshold` → ALERT（赤）
3. **Min/Max 保持**：セッション開始からの t_obj / t_amb の min / max
4. **統計表示**：`--report-interval` ごとに avg / min / max / samples を stderr へ
5. **モック入力**：`--mock-file sample_frames.jsonl` で PC 単体テスト可
6. **エラーハンドリング**：
   - シリアル切断 → 5 秒待って自動再接続
   - JSON パース失敗 → 静かにスキップ
   - Ctrl+C → 統計サマリを表示して正常終了

---

## 6. Nice-to-have（本 PoC の範囲外・将来）

- CSV / JSONL ログ出力（`--log-file`）
- グラフ描画（matplotlib）
- Slack / Bluesky 通知（12-1.9 BCL 経路の流用は非推奨・別記事化）
- CoreS3 側への「アラート通知」フィードバック（USB CDC 逆方向）

---

## 7. Verification Steps

### 常温対象（掌）

1. `python -m apps.ncir_thermometer.thermometer_poc` を起動
2. MLX90614 センサーを掌に向ける（距離 5-10 cm）
3. 期待：`t_obj ≈ 33℃` / `t_amb ≈ 25℃`、Status = NORMAL（緑）

### ハンダゴテ（250-350℃ 想定）

1. ハンダゴテを予熱（350℃ 想定）
2. センサーを**コテ先から 10 cm 程度**離して向ける（**至近距離は避ける・センサー最大 380℃**）
3. 期待：`t_obj ≥ 250℃`、Status = ALERT（赤・点滅）
4. コテを離した瞬間の `t_obj` 降下曲線を目視確認

### Min/Max 挙動

1. ハンダゴテ計測後、離してから統計行を確認
2. 期待：`max t_obj` にコテ先温度が保持されている
3. Ctrl+C で終了時のサマリを確認

### モックモード（PC 単独）

1. `python -m apps.ncir_thermometer.thermometer_poc --mock-file shared/cores3_bridge/tests/sample_frames.jsonl`
2. 期待：sample_frames.jsonl の t_obj / t_amb がループ再生され、閾値判定が動作（nan 行は自動スキップ）

---

## 8. Non-goals（out of scope）

- **医療用途**：本 PoC は電子工作・IoT デバッグ用途に限定。体温計・発熱スクリーニング等の医療機器としての使用は明示的に非対象
- 永続ログ / DB（記事範囲外）
- クラウド送信（12-1.9 BCL パターンの流用は非推奨・別記事化推奨）
- PEC（SMBus CRC-8）検証（HANDOFF_cardputerzero.md の TODO 残・本 PoC では扱わない）

---

## 9. Legal / Safety Notes

- **医療用途ではない旨を UI に明示**（起動時バナー or --help 内）：
  ```
  WARNING: This is a hobby/dev tool. NOT for medical use.
  ```
- **ハンダゴテ実測時の物理安全**：
  - センサーはコテ先から最低 5 cm 以上離す
  - 火傷・煙・引火物に注意
  - 換気推奨
- **MLX90614 センサー保護**：最大測定範囲 -70〜+380℃（データシート値）。実対象がこの範囲を超える場合は非接触でも故障リスクあり

---

## 10. Article Integration（note 12-1.10 執筆用）

### 記事内のコード掲載（Part 2 + Part 3）

- **Part 2**：CoreS3 firmware 側 Arduino コード 30-50 行（`readWordLE()` + レジスタ + `raw × 0.02 − 273.15`）
- **Part 3**：本 PoC の閾値判定コア 30 行程度（Rich TUI 表示ロジックは省略・データ流れに集中）

### 実測データ（2026-08-01 実機 COM5 で取得済み）

- 常温：obj avg=35.8 min=29.8 **max=40.7℃**（150 samples・全域 NORMAL）
- ハンダゴテ：obj avg=64.6 min=29.5 **max=106.2℃**（354 samples・**ALERT 発火**。センサー保護のため 100℃ 超確認で停止）
- 発熱 IC（例：Raspberry Pi CPU 通電後）の温度上昇プロファイル（オプション・未取得）

> ⚠️ **記事の数値整合（要注意）**：冒頭フックの「372℃」は本 PoC の**モック/初期逸話値**であり、
> 今回の安全実測では到達していない（安全のため 106.2℃ で停止）。記事では
> ①実測 106.2℃ を正の数値として使う、②372℃ は「センサー上限 380℃ に迫る理論値／別条件」
> として明確に区別する、のいずれかで**虚偽にならないよう記述**すること。

### 記事の物語軸

- 冒頭：**「ハンダゴテのコテ先を向けた瞬間、赤枠が点り obj が 100℃ を超えた」**（実測 106.2℃・上の注意参照）
- Part 1：MLX90614 IC / SMBus / 視野角 90° / -70〜+380℃ の物理
- Part 2：CoreS3 firmware 側の実装（既実装・SMBus LSB-first）
- Part 3：**本 PoC の Python 側閾値判定 + Min/Max**（本 HANDOFF の成果物）
- Part 4：**CoreS3 ミニシリーズ 7 本振り返り**（12-1.5 → 1.6 → 1.7 → 1.8 → 1.11 → 1.9 → 1.10）
- おわりに：11 月の Cardputer Zero 到着で「12-02 開発日誌」に接続

---

## 11. TODO Checklist

### 実装フェーズ

- [x] `apps/ncir_thermometer/` ディレクトリ作成（アンダースコアへ改名済み）
- [x] `app.yaml` 追加（他アプリと揃える）
- [x] `app-builder.json` 追加（caps=keyboard/filesystem）
- [x] `thermometer_poc.py` 実装（~190 行・閾値コア ~40 行）
- [x] `tests/test_thermometer_poc.py` 実装（閾値判定・統計 6 ケース PASS）

### 動作確認フェーズ

- [x] Rich TUI の表示崩れがないか確認（mock で NORMAL/WARN/ALERT 枠を確認・UTF-8 化で cp932 例外解消）
- [x] 常温計測で NORMAL 状態確認（**実機 COM5・2026-08-01**：150 samples / obj avg=35.8 min=29.8 max=40.7℃・全域 NORMAL）
- [x] ハンダゴテ計測で ALERT 状態確認（**実機 COM5・2026-08-01**：354 samples / obj avg=64.6 min=29.5 **max=106.2℃**・赤表示発火。センサー保護のため 100℃ 超確認で停止）
- [x] Min/Max 保持挙動確認（実機で max=40.7℃ 保持・mock で 372.4℃・単体テスト済み）
- [x] Ctrl+C 終了時のサマリ確認（**実機**：`Summary samples=150 obj avg=35.8 min=29.8 max=40.7 °C`）
- [x] `--mock-file` オプションで PC 単体動作確認（sample_frames.jsonl・nan 行スキップ確認）

### 記事執筆連携フェーズ

- [x] 常温の実測値をキャプチャ（記事 Part 3 用・max=40.7℃/150 samples）
- [x] ハンダゴテの実測値をキャプチャ（冒頭フック用・max=106.2℃/354 samples・§10 の 372℃ 注意参照）
- [ ] 発熱 IC の温度上昇プロファイル（オプション・記事追加素材用・未取得）
- [ ] PoC コード 30 行抜粋を記事に掲載

### PoC 完成後

- [x] `README.md` を他アプリと同じ構造で作成
- [ ] コミット：`feat(ncir-thermometer): App 15 PoC with threshold alerting + min/max keeper`
- [ ] note 12-1.10 執筆へ引き渡し

---

## 12. Related Documents

- **`HANDOFF_cardputerzero.md`**（リポジトリルート）── 全アプリの一次設計書
- **12-1.5 記事ドラフト**（`g:\note\content-lab\articles\drafts\2026-07-11-Cardputer-Zero-M5Stack-CoreS3-センサー先行検証編.md`）── NCIR の初出言及（line 129 付近）
- **12-1.8 記事ドラフト**（`g:\note\content-lab\articles\drafts\2026-08-22-CoreS3-Grove-テスター-INA226.md`）── 同じ Hub Unit 経路の INA226 の実装事例（構成参考）
- **12-1.10 予定記事**（未着手）── 本 PoC 完成後に執筆

---

*本 HANDOFF は Claude Code + Claude API の補助を受けて総司様が設計した仕様書です。実装は総司様ご自身または Claude Code アシスタントが担当します。*
