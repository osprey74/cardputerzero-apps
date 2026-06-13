#!/usr/bin/env python3
"""
INA226-10A 端子動作確認スクリプト

App 13 (tester) の事前検証用。CardputerZero 実機到着後、
PaHUB v2.1 経由で INA226-10A の各端子 (PIN1=INPUT+ / PIN2=INPUT- /
PIN3=OUTPUT- / PIN4=OUTPUT+) が物理ラベル通りに動作するかを確認する。

使い方:
    sudo python3 ina226_terminal_check.py

前提:
    - CardputerZero Raspberry Pi OS 上で実行
    - Grove ポート (I2C, /dev/i2c-1) に PaHUB v2.1 → CH0 → INA226-10A が接続
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

# I2C 設定
I2C_BUS = 1            # CardputerZero の Grove I2C
PAHUB_ADDR = 0x70      # PaHUB v2.1 デフォルト
INA226_ADDR = 0x41     # INA226-10A 固定アドレス
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

# 物理定数
R_SHUNT = 0.005             # 5mΩ (INA226-10A 内蔵)
I_MAX_EXPECTED = 10.0       # ±10A
CURRENT_LSB = I_MAX_EXPECTED / 32767  # ≈ 305.18 µA
CAL_VALUE = int(0.00512 / (CURRENT_LSB * R_SHUNT))  # ≈ 3355


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
            = 0.00512 / (305.18e-6 × 0.005)
            ≈ 3355 = 0x0D1B
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
    print("  ✅ INA226-10A を認識しました。")
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
    print("=" * 60)
    print("INA226-10A 端子動作確認スクリプト")
    print("=" * 60)
    print(f"I2C バス:      /dev/i2c-{I2C_BUS}")
    print(f"PaHUB:        0x{PAHUB_ADDR:02X} (CH{INA226_CH})")
    print(f"INA226-10A:   0x{INA226_ADDR:02X}")
    print(f"シャント:     {R_SHUNT*1000} mΩ (内蔵)")
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

    print("[2/3] INA226-10A のチップ ID を確認...")
    if not verify_chip(bus):
        sys.exit(1)

    print()
    print("[3/3] INA226-10A を初期化...")
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
