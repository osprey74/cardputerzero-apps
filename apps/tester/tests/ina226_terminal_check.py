#!/usr/bin/env python3
"""
INA226 端子動作確認スクリプト (10A 版 / 1A 版 両対応)

App 13 (tester) の事前検証用。CardputerZero 実機到着後、
PaHUB v2.1 経由で INA226 の各端子 (PIN1=INPUT+ / PIN2=INPUT- /
PIN3=OUTPUT- / PIN4=OUTPUT+) が物理ラベル通りに動作するかを確認する。

同一筐体で 2 バリエーションが存在し、内蔵シャント値が異なる:
    - INA226-10A: シャント 5mΩ  / ±10A / Current_LSB ≈ 305µA (広レンジ)
    - INA226-1A : シャント 50mΩ / ±1A  / Current_LSB ≈ 30.5µA (高分解能)
CAL 値は両者とも約 3355（I_MAX×R_shunt が等しいため）だが、生の電流/電力
レジスタを物理量へ換算する Current_LSB が 10 倍違うため、ユニット種別ごとに
定数を切り替える必要がある。混同すると 1A 版の電流が 10 倍で表示される。

使い方:
    sudo python3 ina226_terminal_check.py          # 既定 (UNIT 定数に従う)
    sudo python3 ina226_terminal_check.py 1A       # 1A 版で実行
    sudo python3 ina226_terminal_check.py 10A      # 10A 版で実行

前提:
    - CardputerZero Raspberry Pi OS 上で実行
    - Grove ポート (I2C, /dev/i2c-1) に PaHUB v2.1 → CH0 → INA226 が接続
    - PaHUB の DIP スイッチはデフォルト 0x70
    - smbus2 がインストール済み (pip install smbus2 --break-system-packages)

検証手順 (HANDOFF §3 App 13「動作確認手順」と対応):
    ステップ 1: 何も繋がず実行 → V ≈ 0V, I ≈ 0A であること
    ステップ 2: PIN4 (OUTPUT+) / PIN3 (OUTPUT-) に 5V を直結 → V ≈ 5V
    ステップ 3: USB 5V → PIN1 → PIN4 → 100Ω 抵抗 → PIN3 → USB GND
                → V ≈ 5V, I ≈ 50mA, P ≈ 250mW
    ステップ 4: ステップ 3 の配線を逆 (PIN4 → PIN1) にして I の符号反転を確認
"""

import smbus2
import time
import sys

# ─────────────────────────────────────────────────────────────
# ユニット種別の切替
#   ここを変更するか、コマンドライン引数 (10A / 1A) で上書きする。
# ─────────────────────────────────────────────────────────────
UNIT = "10A"           # 既定のユニット種別 ("10A" | "1A")

# I2C 設定
I2C_BUS = 1            # CardputerZero の Grove I2C
PAHUB_ADDR = 0x70      # PaHUB v2.1 デフォルト
INA226_ADDR = 0x41     # INA226 ユニット固定アドレス (10A/1A 共通、要実機確認)
INA226_CH = 0          # PaHUB の使用チャネル

# INA226 レジスタアドレス
REG_CONFIG       = 0x00
REG_SHUNT_VOLT   = 0x01
REG_BUS_VOLT     = 0x02
REG_POWER        = 0x03
REG_CURRENT      = 0x04
REG_CALIBRATION  = 0x05
REG_MASK_ENABLE  = 0x06
REG_ALERT_LIMIT  = 0x07
REG_MFG_ID       = 0xFE  # 0x5449 ('TI')
REG_DIE_ID       = 0xFF  # 0x2260

# 物理定数（ユニット種別ごとの内蔵シャント値と定格）
#   R_SHUNT   : 内蔵シャント抵抗値 [Ω]
#   I_MAX     : 定格フルスケール電流 [A]（Current_LSB 決定に使用）
UNIT_SPECS = {
    "10A": {"label": "INA226-10A", "r_shunt": 0.005, "i_max": 10.0},
    "1A":  {"label": "INA226-1A",  "r_shunt": 0.05,  "i_max": 1.0},
}


def resolve_unit(unit):
    """UNIT 種別から派生定数 (label, R_SHUNT, CURRENT_LSB, CAL) を算出する。

    Current_LSB = I_MAX / 32767
    CAL = 0.00512 / (Current_LSB × R_shunt)
      ※ I_MAX×R_shunt が 10A/1A で等しい (0.05) ため CAL は両者とも ≈3355。
        物理量への換算係数 Current_LSB のみ 10 倍異なる点が肝。
    """
    if unit not in UNIT_SPECS:
        raise ValueError(f"未知のユニット種別: {unit!r} (有効値: {list(UNIT_SPECS)})")
    spec = UNIT_SPECS[unit]
    r_shunt = spec["r_shunt"]
    current_lsb = spec["i_max"] / 32767
    cal_value = int(0.00512 / (current_lsb * r_shunt))
    return spec["label"], r_shunt, current_lsb, cal_value


# 選択中ユニットの派生定数（main() で CLI 引数により再解決される）
UNIT_LABEL, R_SHUNT, CURRENT_LSB, CAL_VALUE = resolve_unit(UNIT)


def pahub_select(bus, channel):
    """PaHUB v2.1 の指定チャネルだけを有効化する。

    PCA9548A は制御レジスタへの 1byte 書込でチャネルを選択する。
    bit N = 1 で CH N を enable。複数 enable も可能だがアドレス衝突注意。
    """
    bus.write_byte(PAHUB_ADDR, 1 << channel)


def ina226_read16(bus, reg):
    """INA226 から 16bit レジスタを読む (ビッグエンディアン)。"""
    data = bus.read_i2c_block_data(INA226_ADDR, reg, 2)
    return (data[0] << 8) | data[1]


def ina226_write16(bus, reg, value):
    """INA226 へ 16bit レジスタを書く (ビッグエンディアン)。"""
    high = (value >> 8) & 0xFF
    low = value & 0xFF
    bus.write_i2c_block_data(INA226_ADDR, reg, [high, low])


def to_signed16(value):
    """符号なし 16bit を符号付きに変換 (二の補数)。"""
    return value - 0x10000 if value & 0x8000 else value


def init_ina226(bus):
    """INA226 を初期化。Configuration と Calibration を設定。

    Configuration register (0x00):
        AVG[14:12]     = 010 (16 サンプル平均)
        VBUSCT[11:9]   = 100 (バス電圧変換時間 1.1ms)
        VSHCT[8:6]     = 100 (シャント電圧変換時間 1.1ms)
        MODE[2:0]      = 111 (シャント + バス電圧連続変換)
        = 0b0100 0010 0100 0111 = 0x4247

    Calibration register (0x05):
        CAL = 0.00512 / (Current_LSB × R_shunt)
        10A 版: 0.00512 / (305.18e-6 × 0.005) ≈ 3355
        1A  版: 0.00512 / ( 30.52e-6 × 0.05 ) ≈ 3355
        （CAL は同値。換算係数 Current_LSB のみ 10 倍異なる）
    """
    ina226_write16(bus, REG_CONFIG, 0x4247)
    ina226_write16(bus, REG_CALIBRATION, CAL_VALUE)


def verify_chip(bus):
    """Manufacturer ID と Die ID で INA226 の存在を確認。"""
    mfg_id = ina226_read16(bus, REG_MFG_ID)
    die_id = ina226_read16(bus, REG_DIE_ID)
    print(f"  Manufacturer ID: 0x{mfg_id:04X} (期待値: 0x5449 'TI')")
    print(f"  Die ID:          0x{die_id:04X} (期待値: 0x2260)")
    if mfg_id != 0x5449 or die_id != 0x2260:
        print("  ⚠️  ID 不一致。配線・PaHUB チャネル選択・I2C アドレスを確認してください。")
        return False
    print(f"  ✅ {UNIT_LABEL} を認識しました。")
    return True


def read_measurements(bus):
    """V (バス) / V (シャント) / I / P を一回読み取る。"""
    v_bus_raw = ina226_read16(bus, REG_BUS_VOLT)
    v_shunt_raw = to_signed16(ina226_read16(bus, REG_SHUNT_VOLT))
    current_raw = to_signed16(ina226_read16(bus, REG_CURRENT))
    power_raw = ina226_read16(bus, REG_POWER)

    v_bus = v_bus_raw * 1.25e-3          # V (1.25mV LSB)
    v_shunt = v_shunt_raw * 2.5e-6       # V (2.5µV LSB)
    current = current_raw * CURRENT_LSB  # A
    power = power_raw * (CURRENT_LSB * 25)  # W (Power_LSB = 25 × Current_LSB)

    return v_bus, v_shunt, current, power


def main():
    # コマンドライン引数でユニット種別を上書き (未指定なら UNIT 定数)
    global UNIT, UNIT_LABEL, R_SHUNT, CURRENT_LSB, CAL_VALUE
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().upper()
        if arg not in UNIT_SPECS:
            print(f"❌ 未知のユニット種別: {sys.argv[1]!r}")
            print(f"   有効値: {' / '.join(UNIT_SPECS)}")
            sys.exit(1)
        UNIT = arg
    UNIT_LABEL, R_SHUNT, CURRENT_LSB, CAL_VALUE = resolve_unit(UNIT)

    print("=" * 60)
    print(f"{UNIT_LABEL} 端子動作確認スクリプト")
    print("=" * 60)
    print(f"I2C バス:      /dev/i2c-{I2C_BUS}")
    print(f"PaHUB:        0x{PAHUB_ADDR:02X} (CH{INA226_CH})")
    print(f"{UNIT_LABEL}:   0x{INA226_ADDR:02X}")
    print(f"シャント:     {R_SHUNT*1000:g} mΩ (内蔵)")
    print(f"Current LSB:  {CURRENT_LSB*1e6:.2f} µA")
    print(f"Calibration:  {CAL_VALUE} (0x{CAL_VALUE:04X})")
    print()

    try:
        bus = smbus2.SMBus(I2C_BUS)
    except FileNotFoundError:
        print(f"❌ I2C バス /dev/i2c-{I2C_BUS} が見つかりません。")
        print("   raspi-config で I2C を有効化してください。")
        sys.exit(1)

    print("[1/3] PaHUB CH0 を選択...")
    try:
        pahub_select(bus, INA226_CH)
        time.sleep(0.01)
    except OSError as e:
        print(f"❌ PaHUB との通信に失敗: {e}")
        print("   配線・電源・I2C アドレスを確認してください。")
        sys.exit(1)

    print(f"[2/3] {UNIT_LABEL} のチップ ID を確認...")
    if not verify_chip(bus):
        sys.exit(1)

    print()
    print(f"[3/3] {UNIT_LABEL} を初期化...")
    init_ina226(bus)
    time.sleep(0.1)
    print("  ✅ Configuration / Calibration 設定完了")
    print()

    print("計測を開始します (Ctrl+C で終了)")
    print()
    print("時刻       V(bus)    V(shunt)    I          P")
    print("-" * 60)

    try:
        while True:
            v_bus, v_shunt, current, power = read_measurements(bus)
            timestamp = time.strftime("%H:%M:%S")
            # I, P は mA / mW 表記で見やすく
            i_ma = current * 1000
            p_mw = power * 1000
            v_shunt_mv = v_shunt * 1000
            print(
                f"{timestamp}  "
                f"{v_bus:6.3f} V  "
                f"{v_shunt_mv:+7.3f} mV  "
                f"{i_ma:+8.2f} mA  "
                f"{p_mw:8.2f} mW"
            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        print("計測を終了しました。")


if __name__ == "__main__":
    main()
