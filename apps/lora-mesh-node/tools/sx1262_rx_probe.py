#!/usr/bin/env python3
"""App 02 lora-mesh-node ― Cap LoRa-1262 (SX1262) 受信専用プローブ。

CardputerZero 実機上で動かし、Cap LoRa-1262 の配線と初期化手順を確認しつつ、
C6L の Nostos ビーコン(923.000MHz / BW125kHz / SF9 / CR4/5 / 同期語 0x3A)を受信して
RSSI・SNR・CRC を表示する。2026-11-17 に実機で動作確認済み(HANDOFF §9.1)。

⚠️ 受信専用: SetTx / SetTxContinuousWave などの送信コマンドは一切発行しない。
   送信を追加する場合は、Cap LoRa-1262 の工事設計認証(211-251216)の条件
   (922.0〜923.4MHz・125kHz/5mW・1 回 0.4 秒未満・キャリアセンス必須)を満たすこと。

前提(工場出荷イメージに導入済み・sudo 不要):
  - python3-spidev / python3-libgpiod(gpiod 2.x) / i2c-tools
  - pi ユーザーが spi / i2c / gpio グループに所属

配線(CardputerZero):
  SPI   : /dev/spidev0.1 (NSS=GPIO7=SPI0 CE1, SCK=11, MOSI=10, MISO=9), mode 0
  RST   : GPIO26 / BUSY: GPIO22 / DIO1(IRQ): GPIO23
  電源  : EXT 5V 出力(/sys/class/leds/ext_5v_out/brightness)を 1 にして Cap へ給電
  I2C   : PI4IOE5V6408 (0x43) の P0 を出力 High → RF スイッチ(FM8625H)へ給電
  TCXO  : 3.0V を DIO3 から給電 / RF スイッチの送受切替は DIO2

使い方:
  LISTEN=600 python3 sx1262_rx_probe.py     # 600 秒間受信待ち(既定 5 秒)

受信フレームに含まれる位置(緯度・経度)は表示しない。終了時に EXT 5V を元の状態へ戻す。
"""
import os, sys, time, subprocess
import spidev, gpiod
from gpiod.line import Direction, Value

LISTEN = float(os.environ.get("LISTEN", "5"))
L5V = "/sys/class/leds/ext_5v_out/brightness"
RST, BUSY, DIO1 = 26, 22, 23
EXP = "0x43"


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()


def i2cget(reg):
    return int(sh("/usr/sbin/i2cget -y 1 %s 0x%02x" % (EXP, reg)), 16)


def i2cset(reg, val):
    sh("/usr/sbin/i2cset -y 1 %s 0x%02x 0x%02x" % (EXP, reg, val))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def crc8(data):
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


before5v = open(L5V).read().strip()
open(L5V, "w").write("1")
time.sleep(0.6)
req = None
spi = None
try:
    # --- IO expander: P0 (BYPASS -> RF switch supply) = output high
    regs = {r: i2cget(r) for r in (0x01, 0x03, 0x05, 0x07, 0x0B, 0x0D)}
    log("expander before:", " ".join("%02x=%02x" % kv for kv in regs.items()))
    i2cset(0x05, regs[0x05] | 0x01)   # output state high
    i2cset(0x03, regs[0x03] | 0x01)   # direction: output
    i2cset(0x07, regs[0x07] & 0xFE)   # leave high-impedance
    log("expander after: ", " ".join("%02x=%02x" % (r, i2cget(r)) for r in (0x03, 0x05, 0x07)))

    req = gpiod.request_lines("/dev/gpiochip0", consumer="sx1262-rx", config={
        RST: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
        BUSY: gpiod.LineSettings(direction=Direction.INPUT),
        DIO1: gpiod.LineSettings(direction=Direction.INPUT)})
    spi = spidev.SpiDev()
    spi.open(0, 1)
    spi.max_speed_hz = 1000000
    spi.mode = 0

    def busy():
        return req.get_value(BUSY) == Value.ACTIVE

    def dio1():
        return req.get_value(DIO1) == Value.ACTIVE

    def wait(t=1.0):
        t0 = time.time()
        while busy():
            if time.time() - t0 > t:
                raise RuntimeError("BUSY stuck high")
            time.sleep(0.0005)

    def cmd(*b):
        wait()
        return spi.xfer2(list(b))

    def errors():
        r = cmd(0x17, 0, 0, 0)
        return (r[2] << 8) | r[3]

    def irq():
        r = cmd(0x12, 0, 0, 0)
        return (r[2] << 8) | r[3]

    def rssi_inst():
        return -cmd(0x15, 0, 0)[2] / 2.0

    req.set_value(RST, Value.INACTIVE); time.sleep(0.005)
    req.set_value(RST, Value.ACTIVE); time.sleep(0.02)
    wait()
    cmd(0x80, 0x00)                         # SetStandby(RC)
    cmd(0x97, 0x06, 0x00, 0x01, 0x40)       # SetDIO3AsTcxoCtrl(3.0V, 5 ms)
    cmd(0x07, 0x00, 0x00)                   # ClearDeviceErrors
    cmd(0x89, 0x7F); time.sleep(0.05)       # Calibrate(all)
    cmd(0x9D, 0x01)                         # SetDIO2AsRfSwitchCtrl
    cmd(0x96, 0x01)                         # SetRegulatorMode(DC-DC)
    cmd(0x8A, 0x01)                         # SetPacketType(LoRa)
    cmd(0x86, 0x39, 0xB0, 0x00, 0x00)       # SetRfFrequency(923.000 MHz)
    cmd(0x98, 0xE1, 0xE9); time.sleep(0.05) # CalibrateImage(902-928)
    cmd(0x8B, 0x09, 0x04, 0x01, 0x00)       # SF9, BW125, CR4/5, LDRO off
    cmd(0x8C, 0x00, 0x08, 0x00, 0xFF, 0x01, 0x00)  # preamble 8, explicit hdr, max len, CRC on, std IQ
    cmd(0x0D, 0x07, 0x40, 0x34, 0xA4)       # LoRa sync word 0x3A (RadioLib encoding)
    cmd(0x8F, 0x00, 0x00)                   # SetBufferBaseAddress
    cmd(0x0D, 0x08, 0xAC, 0x96)             # RX boosted gain
    cmd(0x08, 0x02, 0x66, 0x02, 0x62, 0x00, 0x00, 0x00, 0x00)  # IRQ mask / DIO1 mask
    st = cmd(0xC0, 0x00)[1]
    log("after init: chipmode=%d errors=0x%04x" % ((st >> 4) & 7, errors()))
    r = cmd(0x1D, 0x07, 0x40, 0x00, 0, 0)
    log("sync word reg readback:", hex(r[4]), hex(r[5]))

    # --- DIO1 (IRQ) check via RX timeout
    cmd(0x02, 0xFF, 0xFF)
    log("DIO1 before SetRx:", int(dio1()))
    t0 = time.time()
    cmd(0x82, 0x00, 0x7D, 0x00)             # SetRx(timeout 0.5 s)
    seen = None
    while time.time() - t0 < 2.0:
        if dio1():
            seen = time.time() - t0
            break
        time.sleep(0.002)
    log("DIO1 rose after %.3f s" % seen if seen is not None else "DIO1 did NOT rise", "irq=0x%04x" % irq())
    cmd(0x02, 0xFF, 0xFF)
    log("DIO1 after clear:", int(dio1()))

    # --- continuous RX: noise floor + packets
    cmd(0x82, 0xFF, 0xFF, 0xFF)
    time.sleep(0.05)
    s = [rssi_inst() for _ in range(40) if not time.sleep(0.025)]
    log("RSSI inst (1 s): min %.1f avg %.1f max %.1f dBm" % (min(s), sum(s) / len(s), max(s)))
    log("listening %.0f s on 923.000 MHz BW125 SF9 sync 0x3A ..." % LISTEN)
    end = time.time() + LISTEN
    nrx = 0
    peak = -200.0
    nextstat = time.time() + 60
    while time.time() < end:
        if dio1():
            f = irq()
            if f & 0x0002:
                r = cmd(0x13, 0, 0, 0)
                n, start = r[2], r[3]
                data = cmd(0x1E, start, 0x00, *([0] * n))[3:]
                ps = cmd(0x14, 0, 0, 0, 0)
                rssi, snr = -ps[2] / 2.0, (ps[3] - 256 if ps[3] > 127 else ps[3]) / 4.0
                nrx += 1
                info = "len=%d rssi=%.1f dBm snr=%.2f dB lora_crc=%s" % (n, rssi, snr, "ERR" if f & 0x0040 else "ok")
                if n == 16:
                    info += " | nostos frame: version=%d flags=0x%02x seq=%d crc8=%s (position not shown)" % (
                        data[0], data[1], data[2], "ok" if crc8(data[:15]) == data[15] else "BAD")
                log("RX", info)
            else:
                log("irq=0x%04x" % f)
            cmd(0x02, 0xFF, 0xFF)
        else:
            v = rssi_inst()
            peak = max(peak, v)
            if time.time() > nextstat:
                log("... still listening, peak RSSI so far %.1f dBm, packets %d" % (peak, nrx))
                nextstat += 60
            time.sleep(0.01)
    log("done: packets=%d peak RSSI %.1f dBm errors=0x%04x" % (nrx, peak, errors()))
    cmd(0x80, 0x00)
finally:
    if spi:
        spi.close()
    if req:
        req.release()
    open(L5V, "w").write(before5v)
    log("ext_5v_out restored to", before5v)
