# App 13: Tester

ブレッドボード電子工作のお供となる簡易テスター。INA226-10A + PaHUB v2.1
経由で DC 電圧 / 電流 / 電力を CardputerZero LCD に表示する。

仕様詳細は [HANDOFF_cardputerzero.md §3 App 13](../../HANDOFF_cardputerzero.md) を参照。

## ハードウェア要件

- M5Stack Unit INA226-10A（絶縁型 ±10A / 30V）
- M5Stack PaHUB v2.1（Port A I2C 拡張ハブ）
- Chain Encoder × 2（2.54mm UART ヘッダ経由）

## ディレクトリ構成

```
tester/
├── README.md
├── tests/
│   └── ina226_terminal_check.py   # 端子動作確認 PoC スクリプト
└── (今後追加予定: app.yaml, src/, assets/)
```

## 事前検証スクリプト

実機到着後、本格実装の前に以下スクリプトで端子動作を確認する:

```bash
# 依存パッケージ
pip install smbus2 --break-system-packages

# 実行
sudo python3 tests/ina226_terminal_check.py
```

スクリプト本体のヘッダコメントに 4 ステップの検証手順を記載済み。
