# CardputerZero 到着時調査まとめ（note 記事用資料）

- 調査日: 2026-11-17（到着当日）
- 対象: M5Stack CardputerZero 本体（Kickstarter 版・標準モデル）、Cap LoRa-1262、Cap CC1101
- 参考として、手元の関連機器（Unit C6L、PaperMono、CoreS3）の技適も同じ方法で照合した（7.7 節）
- この資料の位置づけ: 記事を書くための下調べ資料です。事実・数値・出典を項目別に並べています。文章はそのまま使う前提ではありません。
- 確度の表記: 【実測】＝実機で確認／【公式】＝公式の文書・データベース・回路図に記載／【推定】＝状況からの推測で未確認

---

## 0. 記事の柱になりそうな発見（要約）

1. **技適は「番号がある」だけでは足りず、認証された条件が狭い。** Cap LoRa-1262 の LoRa は 922.0〜923.4MHz の 8 波、125kHz 幅で 5mW、1 回の送信 0.4 秒未満。920MHz 帯の一般的な上限（20mW）ではなく、機器ごとの認証値が上限になる。
2. **付属アンテナは「868MHz」表記だが、それが認証アンテナ。** 表記が合う市販の 920MHz 用アンテナに替えると、かえって認証の範囲外になる。
3. **公式ドキュメントや回路図のピン番号は Cardputer-ADV（ESP32-S3）用。** CardputerZero では番号がまったく違い、Raspberry Pi 標準の SPI0・I2C1・UART に載る。
4. **Cap は本体の 5V 出力を入れないと動かない。** 標準アプリは起動時に 5V を入れ、終了時に切っている。
5. **画面は SDL でも Wayland でもなく、フレームバッファへの直接描画。** 標準ランチャーも標準アプリも `/dev/fb0` に直接描き、キーボードは入力デバイスを直接読む。
6. **「512MB」のうち OS から見えるのは 352MB。** 画面用メモリの設定を 128MB から 64MB に変えると 415MB になり、カメラも動いた。
7. **Kickstarter で告知されたカメラ不具合の正体は、Camera アプリと libcamera の版の食い違い。** 告知の修正手順は、配布元の更新で成立しなくなっていた。
8. **OS は Debian 13（trixie）、Python は 3.13。** Bookworm ではない。

---

## 1. 本体の基本情報

### 1.1 システム【実測】

| 項目 | 内容 |
|---|---|
| モデル表記 | Raspberry Pi Compute Module 0 Rev 1.0 |
| OS | Debian GNU/Linux 13 (trixie) |
| カーネル | 6.18.39+rpt-rpi-v8（aarch64） |
| Python | 3.13.5 |
| ストレージ | microSD 約 29GB（起動用 FAT32 0.5GB＋Linux 28.6GB）、出荷時の使用量 5.9GB |
| ホスト名 | CardputerZero（`cardputerzero.local` で到達可能） |
| Wi-Fi の規制域 | JP（`iw reg get` の結果。起動オプションには `regdom=AE` の記載があるが、実効値は JP） |
| カーネル関連パッケージ | 出荷時点で `apt-mark hold`（固定）されている |
| 更新可能なパッケージ | 約 150 個（出荷イメージのまま `apt update` した時点） |

### 1.2 初回起動とセットアップ

- 電源スイッチを右へスライドして起動。初回は時間がかかる。【公式】
- セットアップウィザードで、ユーザー名、ネットワーク、SSH の有効化を設定する。既定のユーザー名・パスワードは無い。【公式】
- ユーザー名を `pi` にした場合、`ssh pi@cardputerzero.local` で接続できた。【実測】
- `sudo` はパスワードが必要。`pi` は dialout・spi・i2c・gpio・video・input などのグループに最初から所属している。【実測】
- 再インストールは M5 Imager で microSD をカードリーダーから焼く方法が推奨。USB 経由（rpiboot）は非推奨。【公式】

### 1.3 知っておくべき注意点【公式】

- **Cap はホットプラグ不可。** 着脱は電源を切ってから。
- **Grove と上部 EXT の 5V 出力は既定で OFF。** Settings > ExtPort で有効にする。
- ADB は Settings > Developer で有効化し、USB Switch を Slave にして USB-C2 から接続する。
- ソフトでシャットダウンしたあと、スイッチを左に戻して電源を切る。
- 地磁気センサ（BMM150）は Kickstarter 版のみ搭載。生産終了品のため、将来の一般販売版には載らない（KS Update #11）。Lite 版はもともと IMU なし。

### 1.4 プリインストールアプリ【実測】

| パッケージ | 版 |
|---|---|
| applaunch（標準ランチャー） | 0.6.105 |
| camera | 1.0.2-m5stack1 |
| factorytest | 1.0.0-m5stack1 |
| m5cardputerzero-cap-lora-1262（LoRa） | 1.0.1-m5stack1 |
| m5cardputerzero-cap-lora-1262-gps（GPS） | 1.0.0 |
| m5cardputerzero-cap-cc1101-nfc（NFC） | 1.0.1 |
| m5cardputerzero-cap-cc1101-subg-chat（SubG Chat） | 1.0.1 |
| m5cardputerzero-compass | 0.2.4 |
| m5cardputerzero-files | 1.0.2 |
| m5cardputerzero-ir-chat / ir-remote | 0.1.3 / 0.1.4 |
| m5cardputerzero-keyboard-guide | 1.0.1 |
| m5cardputerzero-music / piano / recorder | 0.1.7 / 0.1.1 / 0.1.8 |

開発に使えるものとして、gcc、i2c-tools、Python の `spidev`・`pyserial`・`gpiod`（2.2.0）・`numpy`（2.2.4）・Pillow（11.1.0）・`picamera2`（0.3.37）、`rpicam-apps`（1.13.0）が最初から入っている。cargo と gpsd は入っていない。

---

## 2. メモリ

### 2.1 出荷時の状態【実測】

| 項目 | 値 |
|---|---|
| 搭載メモリ | 512MB |
| 画面用（GPU）の割り当て | 128MB（`config.txt` の `gpu_mem=128`） |
| OS から見える合計 | 約 352MB（MemTotal 361,392kB） |
| 空き（アイドル時） | 110〜150MB |
| スワップ | 約 351MB。**microSD ではなく zram（メモリ内の圧縮領域、zstd）** |

- 測定時、zram には 131MB 分のデータが約 27MB に圧縮されて入っていた。

### 2.2 何がメモリを使っているか【実測】

本体は Raspberry Pi OS のデスクトップ一式（lightdm の自動ログイン、labwc、パネル、デスクトップ表示）を起動し、それとは別に標準ランチャーを動かしている。

| プロセス | 実メモリ（PSS） | スワップ内 | 役割 |
|---|---|---|---|
| pipewire 一式 | 約 22MB | 約 13MB | 音声 |
| wf-panel-pi | 約 10MB | 約 9MB | デスクトップのパネル |
| 標準ランチャー | 約 10MB | 約 5MB | ランチャー |
| pcmanfm | ほぼ 0MB | 約 13MB | デスクトップ表示 |
| labwc | 約 1MB | 約 9MB | ウィンドウ管理 |

- 標準ランチャー自体は軽い。自作ランチャーに置き換えても、浮くのは 10MB 程度。

### 2.3 画面用メモリを減らす【実測】

`/boot/firmware/config.txt` の `gpu_mem=128` を `gpu_mem=64` に変更して再起動した結果。

| 項目 | 変更前 | 変更後 |
|---|---|---|
| OS から見える合計 | 352MB | 415MB（MemTotal 424,752kB） |
| スワップ（zram） | 351MB | 414MB |
| 画面側のメモリ確保の失敗 | 0 件 | 0 件 |
| カメラ（プレビューと撮影） | 動作 | 動作 |

- 64MB は、このクラスの Raspberry Pi の標準値。M5Stack が 128MB にしている理由は不明。【推定】カメラの画像処理に余裕を持たせるためと思われる。
- 動画撮影や長時間のカメラ使用は未確認。

---

## 3. 画面・キーボード・標準ランチャーの仕組み【実測】

自作アプリを作るうえで最も重要だった発見。

| 項目 | 内容 |
|---|---|
| 液晶 | `/dev/fb0`（ドライバ名 panel-mipi-dbi）。320×170、16bpp（RGB565）、1 行 640 バイト |
| キーボード | 入力デバイス `tca8418c`（`/dev/input/by-path/platform-3f804000.i2c-event`） |
| 標準ランチャー | `/usr/share/APPLaunch/bin/M5CardputerZero-APPLaunch`。systemd のユーザーサービス `APPLaunch.service` として動く |
| 描画の方式 | ランチャーも標準アプリも、**フレームバッファへ直接描画**する。SDL、Wayland、X のライブラリはリンクしていない |
| アプリの登録 | `/usr/share/APPLaunch/applications/<名前>.desktop` |
| アイコン | `/usr/share/APPLaunch/share/images/` に置く。100×100 または 90×90 の RGBA PNG |
| アプリ起動時 | ランチャーは自分のキーボード処理を止め、アプリの終了を待つ。入力デバイスは排他取得せず、アプリと共有する |
| アプリの終了 | ESC の長押しで、ランチャーがアプリを終了させてホームに戻る |
| root が要るアプリ | `Exec=/usr/bin/sudo -n -- <バイナリ>` と `/etc/sudoers.d/` の個別許可で対応している |

- SDL2 のライブラリ自体は入っているが、SDL2 のウィンドウは液晶に出ない。
- SSH から直接アプリを起動すると、ランチャーが描画とキー処理を続けるため、電波・電池・時刻の表示が重なり、キーも両方に届く。ランチャーから起動すれば起きない。
- ランチャーの再起動は `systemctl --user restart APPLaunch`（`sudo` 不要）。

登録ファイルの例（標準の GPS アプリ）:

```ini
[Desktop Entry]
Name=GPS
Exec=/usr/bin/sudo -n -- /usr/share/APPLaunch/bin/M5CardputerZero-Cap-LoRa-1262-GPS
Terminal=false
Icon=share/images/cap-lora-1262-gps.png
Type=Application
```

---

## 4. 内蔵デバイスとピン【実測】

### 4.1 I2C（`/dev/i2c-1`）

| アドレス | デバイス | 備考 |
|---|---|---|
| 0x10 | BMM150（地磁気） | Kickstarter 版のみ。カーネルドライバが使用中 |
| 0x32 | RX8130CE（RTC） | `/dev/rtc0` |
| 0x34 | TCA8418（キーボード） | |
| 0x4f | 【推定】M5Stack 独自の IO エキスパンダ | GPIO チップ `m5ioe1`（14 本）と IIO デバイス `m5ioe1`（電圧・温度）として見える。5V 出力の制御線などがここにある |
| 0x55 | BQ27220（電池残量計） | |
| 0x68 | BMI270（加速度・ジャイロ） | |

### 4.2 センサ（Linux IIO）

| IIO デバイス | 読める値 | 補足 |
|---|---|---|
| bmm150 | `in_magn_{x,y,z}_raw` | 10Hz、scale 0.000625 |
| bmi270 | `in_accel_*_raw`、`in_anglvel_*_raw` | 加速度 100Hz |
| m5ioe1 | `in_voltage*_raw`、`in_temp4_raw` | |

- `pi` ユーザーのまま、ファイルを読むだけで値が取れる。追加パッケージは不要。
- 地磁気は、較正しないと本体内部の磁気（スピーカーの磁石など）に埋もれて方位が動かない。
- 地磁気センサは、加速度センサに対して裏返しの向きで載っている（x と z の符号が逆）。全方位に転がす較正で自動判定した結果。

### 4.3 GPIO と各バス

| 機能 | 割り当て |
|---|---|
| SPI0 CS0（GPIO8） | 液晶 |
| SPI0 CS1（GPIO7） | Cap 用。`/dev/spidev0.1` |
| 液晶の制御 | GPIO24（enable）、GPIO25（dc） |
| UART | `/dev/serial0` → `/dev/ttyS0`（GPIO14／15） |
| 赤外線 | GPIO12（送信）、GPIO13（受信） |
| ヘッドホン検出 | GPIO17 |
| カメラ | IMX219（`dtoverlay=imx219`）、`/dev/video0` |

### 4.4 `config.txt` の主な内容

```
gpu_mem=128
dtparam=i2c_arm=on / i2s=on / spi=on
dtoverlay=vc4-kms-v3d,cma-64
dtoverlay=imx219
enable_uart=1
dtoverlay=dwc2
dtoverlay=cardputerzero-v5-overlay
dtoverlay=bq27220_v5
dtoverlay=bmi270_bmm150_overlay
dtoverlay=gpio-ir,gpio_pin=13,gpio_pull=up
dtoverlay=gpio-ir-tx,gpio_pin=12
```

---

## 5. 電池の持ち（Kickstarter Update #15 の公式試験）【公式】

条件: 新品、出荷時イメージ、追加アプリなし、輝度 100%、5 分間隔でサンプリング。

| 使い方 | 画面 | Wi-Fi / BT | 駆動時間 |
|---|---|---|---|
| カメラ連続プレビュー | 常時点灯 | 接続 / ON | 2 時間 20 分 |
| 動画連続再生（online） | 常時点灯 | 接続 / ON | 4 時間 15 分 |
| 動画連続再生（offline） | 常時点灯 | OFF / OFF | 4 時間 50 分 |
| スタンバイ（online） | 30 秒で消灯 | 接続 / ON | 5 時間 20 分 |
| スタンバイ（offline） | 30 秒で消灯 | OFF / OFF | 5 時間 25 分 |

- 充電は、低残量から 100% まで平均約 2 時間 5 分（3 回、2 時間〜2 時間 10 分）。
- 無線の ON／OFF による差は 5 分しかない。
- 【推定】公称 1750mAh×3.7V≒6.5Wh から逆算すると、待機で約 1.2W、カメラ使用時で約 2.8W。
- グラフでは、残量表示が約 7% で横ばいになったあとに停止している。

---

## 6. カメラ不具合の正体

### 6.1 告知の内容（Kickstarter Update #15、2026-11-10）【公式】

- ソフト更新や追加アプリの導入後に、カメラが動かなくなる報告がある。ハードの故障ではない。
- カメラが動いているなら、現状の構成を維持し、不要な更新を避ける。
- 対処は 3 つ。公式 OTA を待つ／Camera 1.0.3 と FactoryTest 1.0.2 を手動で入れる／出荷時イメージを書き戻す。

### 6.2 実機で再現して分かったこと【実測】

告知どおり Camera 1.0.3 を入れたところ、Camera アプリが起動しなくなった。ログに出たエラーは次のとおり。

```
/usr/bin/camera_app: symbol lookup error: /usr/bin/camera_app:
undefined symbol: _ZN9libcamera10properties22PixelArrayReadableAreaE
```

原因は、Camera アプリがビルド時の libcamera の版に依存していること。

| Camera アプリ | 公開日 | 対応する libcamera |
|---|---|---|
| 1.0.2（出荷時） | 2026-09-22 | 0.7.2+rpt20260817（出荷時） |
| 1.0.3 | 2026-11-03 | 0.7.2+rpt20261009 |
| 1.0.4 | 2026-11-13 | 0.8.0+rpt20261104（`libcamera0.8`） |

- Camera 1.0.3 のパッケージは、依存の指定が `libcamera0.7 (>= 0.7.2)` と緩い。そのため libcamera が更新されないまま入ってしまう。
- 対になる FactoryTest 1.0.2 は `libcamera0.7 (>= 0.7.2+rpt20261009)` を要求する。しかし Raspberry Pi の配布元は 11 月 4 日に libcamera 0.8 へ移行しており、必要な `libcamera-ipa` の同じ版が通常の方法では入らない。導入の試算は依存関係エラーで失敗した。
- つまり、**告知（11 月 10 日）の手動手順は、調査時点では成立しなかった。**
- M5Stack は 11 月 13 日に、libcamera 0.8 向けの Camera 1.0.4 と FactoryTest 1.0.3 を公開している。

### 6.3 復旧と教訓【実測】

- GitHub から Camera 1.0.2 を取得し、`sudo apt install --allow-downgrades ./Camera_1.0.2_m5stack1_arm64.deb` で戻して復旧した。変更されたのは `camera` パッケージ 1 つだけ。
- `.deb` を入れる前に、`dpkg-deb -f <deb> Depends` で依存を読み、`apt-get -s install <deb>` の試算で実際に何が更新・削除されるかを確かめるべきだった。
- libcamera 0.8 系に進める場合の試算では、12 個更新、1 個追加、4 個削除になる。
- 作業前に microSD を丸ごとバックアップしておくと安心。Windows なら、管理者権限の Git Bash で `dd if=/dev/sdX of=backup.img bs=4M status=progress`。

---

## 7. 技適（工事設計認証）

実機のラベルで番号を確認し、総務省の「技術基準適合証明等を受けた機器の検索」と、そこに添付されている試験成績書で内容を確かめた。

### 7.1 3 機器の一覧【公式】

| 項目 | 本体（Compute Module 0） | Cap LoRa-1262 | Cap CC1101 |
|---|---|---|---|
| 工事設計認証番号 | 020-260249 | 211-251216 | 219-269336 |
| 認証日 | 令和8年9月28日 | 令和8年2月12日 | 令和8年8月21日 |
| 認証を受けた者 | Raspberry Pi Limited | M5Stack Technology Co., Ltd | M5Stack Technology Co., Ltd |
| 型式 | Raspberry Pi Compute Module 0 又は Compute Module Zero | Cap LoRa-1262 | Cap CC1101 |
| 種別 | 第2条第19号 | 第2条第8号 | 第2条第8号 |
| 認証機関 | (一社)TAC（登録証明機関） | Bay Area Compliance Laboratories Corp（MRA） | KL-Certification GmbH（MRA） |
| FCC ID（ラベル） | — | 2AN3WM5CAPLORA1262 | 2AN3WM5CAPCC1101 |

### 7.2 本体（Compute Module 0）【公式】

- Wi-Fi: 2412〜2472MHz（5MHz 間隔 13 波）。G1D 0.007W/MHz、D1D・G1D 0.004W/MHz。
- Bluetooth: 2402〜2480MHz（40 波）F1D 0.005W、ほか 2441MHz の区分。
- 5GHz 帯の記載はない。
- 試験成績書（DEKRA）の申請アンテナは 3 種類。その 1 つが **「CardputerZero」と名指しされた FPC アンテナ**（型番 R-CardputerZero v2.0、利得 0.071dBi）。ほかは ED-ANT-C（FPC、3.5dBi）と外付け YH2400-5800-SMA-108（2dBi）。
- Raspberry Pi 側が、CardputerZero への搭載を前提に認証を取っていることになる。認証日は出荷開始の直前。

### 7.3 Cap LoRa-1262【公式】

総務省データベースの記載: F1D 922〜923.4MHz（200kHz 間隔 8 波）1.5〜5.0mW

試験成績書（Shenzhen Accurate Technology、2504A09666E-RF）で分かる条件:

| 項目 | 内容 |
|---|---|
| 周波数 | 922.0〜923.4MHz、200kHz 刻みの 8 波 |
| 変調 | LoRa |
| 帯域幅と定格出力 | 125kHz＝5mW、500kHz＝1.5mW（250kHz は試験対象外） |
| 出力の実測 | 125kHz で約 4.5mW（EIRP 8.7dBm） |
| 占有帯域幅の実測 | 約 127kHz（上限 200kHz）、約 505〜510kHz（上限 600kHz） |
| 送信時間 | 1 回 0.4 秒未満、休止 2ms 超、1 時間の合計 720 秒未満（1 チャネル 360 秒未満） |
| キャリアセンス | 必須（−80dBm で送信しない） |
| アンテナ | 申請利得 2.14dBi |
| 試験時の親機 | Cardputer-ADV（M5Stack のエンジニアリングモード） |

### 7.4 Cap CC1101【公式】

総務省データベースの記載: F1D 315〜315MHz 0.04mW／F1D 922〜923.4MHz 75mW

| 項目 | 922〜923.4MHz | 315MHz |
|---|---|---|
| 試験成績書 | AiT、AiTDG-260609002W10 | AiT、AiTDG-260609002W9 |
| 周波数 | 922.0／922.8／923.4MHz の 3 波 | 315MHz の 1 波 |
| 変調 | FSK | FSK、片方向通信 |
| 定格出力 | 75mW（実測約 75mW。試験上の上限は 0.25W） | EIRP 0.04mW（上限 250µW） |
| 占有帯域幅 | 165〜184kHz（上限 200kHz） | — |
| 送信時間 | 4 秒以下、休止 50ms 以上 | 送信時間制限装置が要件 |
| キャリアセンス | 必須（−74dBm、5ms 以上） | — |
| アンテナ | 申請利得 2.14dBi | 申請利得 −3.13dBi |

- **433MHz・868MHz・915MHz は認証の対象外。** 国内では送信できず、受信のみ。
- 922MHz 帯の試験成績書では、区分が「UHF RFID」と書かれている。75mW が 920MHz 帯の特定小電力の一般的な上限（20mW）より大きい理由は、この区分にあると思われる。【推定】詳しい制度上の位置づけは未確認。
- NFC（13.56MHz）は、この認証番号の記載には含まれていない。扱いは未確認。

### 7.5 アンテナの表記と認証の関係【公式】

付属アンテナの表記は、認証された周波数と合っていないように見える。

| Cap | 付属アンテナの表記 | 試験成績書での扱い |
|---|---|---|
| Cap LoRa-1262 | 868MHz（1 本） | 外観写真の「ANT」が同じ形の黒いホイップ。ラベルの末尾「…8MHz」が読める |
| Cap CC1101 | 868MHz | 構造写真に「920MHz Antenna」と注記されているのが、ラベル「868…」のアンテナ |
| Cap CC1101 | 315MHz | 構造写真に「315MHz Antenna」と注記 |
| Cap CC1101 | 433MHz | 試験成績書に登場しない（認証構成に含まれない、受信用） |

- 工事設計認証は、申請時のアンテナを含めた設計に対して与えられる。付属の 868MHz 表記アンテナで 922MHz 帯を使うのが、認証どおりの使い方になる。
- 868MHz と 922MHz の差は約 6%。この種の小型アンテナは帯域に幅がある。【推定】
- 世界共通の同梱品に、日本向けの認証を後から取った構成と思われる。【推定】

### 7.6 Meshtastic との関係【推定を含む】

1 パケットの送信時間の計算値（プリアンブル 16、明示ヘッダ、CRC あり。バイト数は Meshtastic の 16 バイトヘッダ込み）。

| 設定 | 20B | 32B | 48B | 64B | 100B | 0.4 秒未満か |
|---|---|---|---|---|---|---|
| 125kHz SF7 | 65ms | 80ms | 106ms | 126ms | 183ms | 収まる |
| 125kHz SF8 | 119ms | 150ms | 191ms | 232ms | 324ms | 収まる |
| 125kHz SF9 | 218ms | 280ms | 341ms | 423ms | 587ms | 48B 程度まで |
| 125kHz SF10 | 436ms | 518ms | 641ms | 764ms | 1092ms | 超える |
| 125kHz SF12（CR4/8） | 1974ms | 2761ms | — | — | — | 超える |
| 500kHz SF7 | 16ms | 20ms | 26ms | 32ms | 46ms | 収まる（1.5mW） |
| 500kHz SF9 | 55ms | 70ms | 85ms | 106ms | 147ms | 収まる（1.5mW） |
| 250kHz SF11（LongFast） | 395ms | 477ms | 600ms | 723ms | 1010ms | 帯域幅が試験対象外、時間も超える |

- 送信時間は計算値。Meshtastic のプリセット名と設定値の対応は、公式での確認が必要。
- 既定の LongFast（250kHz 幅、SF11）は、帯域幅が試験対象に無く、送信時間も 0.4 秒を超えやすい。この Cap からそのまま送信するのは難しいと考えられる。【推定】
- 到達距離を稼ぐ SF11・SF12 が使えないため、送信側として使う場合の距離は短くなる。
- **受信には技適上の制約がない。** 受信専用で使うぶんには、帯域幅や SF を自由に選べる。

### 7.7 関連機器の技適（Unit C6L、PaperMono、CoreS3）【公式】

CardputerZero と組み合わせて使う手元の M5Stack 製品も、同じ方法（本体の表示 → 総務省データベース → 添付の試験成績書）で照合した。いずれも認証を受けた者は M5Stack Technology Co., Ltd、新スプリアス規定。

#### 一覧

| 項目 | Unit C6L | PaperMono | CoreS3 |
|---|---|---|---|
| 工事設計認証番号 | 211-250603 | 211-260514 | 219-239073 |
| 認証日 | 令和7年9月9日 | 令和8年8月11日 | 令和5年3月13日 |
| 登録の件数 | 2 件（同じ番号で種別ごと） | 2 件（同じ番号で種別ごと） | 1 件 |
| 第2条第8号（920MHz 帯 LoRa） | あり | あり | なし |
| 第2条第19号（2.4GHz 帯） | あり | あり | あり |
| 認証機関 | Bay Area Compliance Laboratories Corp（MRA） | Bay Area Compliance Laboratories Corp（MRA） | KL-Certification GmbH（MRA） |

- C6L と PaperMono は、**同じ認証番号で 2 件登録されている**（LoRa の分と、2.4GHz の分）。番号で検索すると 2 件出てくるので、両方を見る必要がある。

#### LoRa（第2条第8号）の条件の比較

| 項目 | Cap LoRa-1262 | Unit C6L | PaperMono |
|---|---|---|---|
| 総務省データベースの記載 | F1D 922〜923.4MHz（200kHz 間隔 8 波）1.5〜5.0mW | F1D 922〜923.4MHz（200kHz 間隔 8 波）1.5〜5.0mW | F1D 922〜923.4MHz（200kHz 間隔 8 波）7mW |
| 試験成績書 | ATC、2504A09666E-RF | ATC、2504U29565E-RF | ATC、2604T59816E-RF |
| 125kHz 幅の定格出力 | 5mW | 5mW | **試験対象外** |
| 500kHz 幅の定格出力 | 1.5mW | 1.5mW | 7mW |
| アンテナの申請利得 | 2.14dBi（付属ホイップ） | 1.67dBi | −6.13dBi（内蔵） |
| 送信時間 | 1 回 0.4 秒未満、1 時間の合計 720 秒未満（1 チャネル 360 秒未満） | 同じ | 同じ |
| キャリアセンス | 必須 | 必須 | 必須 |

- **周波数（8 波）と送信時間の条件は 3 機種で共通。** 違うのは、使える帯域幅と出力。
- **Cap LoRa-1262 と Unit C6L は、LoRa の条件がまったく同じ。**
- **PaperMono は 500kHz 幅だけが試験対象。** 125kHz 幅での送信は認証に含まれない。
- 3 機種すべてが送信できる共通の帯域幅は、500kHz だけになる。125kHz 幅で送信できるのは、Cap LoRa-1262 と C6L の 2 機種。
- PaperMono の登録値は 7mW だが、内蔵アンテナの利得が低い。試験成績書上の EIRP は約 0.5dBm（約 1.1mW）で、実際に空間へ出る電力は小さい。
- 受信には制約がないので、「C6L が 125kHz 幅で送信し、PaperMono と CardputerZero が受信する」という片方向の構成は成り立つ。
- 8.5 節の受信試験で受けたビーコンは、Unit C6L に入れた自作のもの（923.0MHz、125kHz 幅、+6dBm、送信前にキャリアセンス）。C6L の認証条件に収めた設定にしている。

#### 2.4GHz 帯（第2条第19号）の比較

| 項目 | Unit C6L | PaperMono | CoreS3 | 参考: Compute Module 0 |
|---|---|---|---|---|
| Bluetooth（2402〜2480MHz） | F1D 40 波、2mW | F1D 40 波、1.5〜2mW | F1D、1.5mW | F1D 40 波、5mW |
| Wi-Fi 11b（2412〜2472MHz） | 4mW/MHz | 4.8mW/MHz | 0.5mW/MHz | 7mW/MHz（G1D） |
| Wi-Fi 11g | 2mW/MHz | 1.5mW/MHz | 0.5mW/MHz | 4mW/MHz（D1D・G1D） |
| Wi-Fi 11n（20MHz 幅） | 2mW/MHz | 1.0mW/MHz | 0.3mW/MHz | 上の 4mW/MHz の区分に含まれると思われる【推定】 |
| Wi-Fi 11n（40MHz 幅、2422〜2462MHz） | 1mW/MHz | 0.5mW/MHz | 0.3mW/MHz | 記載なし |
| アンテナの申請利得 | 2.77dBi | 0.84dBi | 2.46dBi（内蔵メタルアンテナ） | 0.071dBi（CardputerZero 用 FPC） |

- Wi-Fi の値は、C6L・PaperMono・CoreS3 が試験成績書の定格値、Compute Module 0 が総務省データベースの記載値。C6L は 11ax（20MHz 幅）も 2mW/MHz で試験されている。
- 2.4GHz 帯は、標準のファームウェアや OS の設定で使うかぎり、LoRa のように出力や送信時間を利用者が管理する場面は基本的にない。【推定】
- CoreS3 は LoRa を持たないので、第2条第19号の 1 件だけ。

#### ここから言えること

- **「920MHz 帯は 20mW まで」という一般的な理解は、個々の機器には当てはまらない。** 調べた 3 機種の LoRa は、いずれも 5〜7mW が上限だった。
- **同じメーカーの LoRa 機器でも、使える帯域幅が違う。** 相互に通信させるなら、全機の条件を並べて、共通して使える設定を選ぶ必要がある。
- **認証番号の検索結果には、試験成績書が添付されている。** データベースの 1 行（周波数と出力）だけでは分からない帯域幅、送信時間、アンテナの条件は、そこで確認できる。

---

## 8. Cap LoRa-1262

### 8.1 構成【公式】（回路図 Cap V1.1、Stamp LoRa-1262 Mini）

| 部品 | 内容 |
|---|---|
| LoRa | SX1262（Stamp LoRa-1262 Mini モジュール） |
| GPS | GP-02（ATGM336H、AT6668）、115200bps、アンテナ内蔵 |
| GPS の増幅器 | MAX2659。SHDN 端子が電源に直結で、常時 ON |
| IO エキスパンダ | PI4IOE5V6408、I2C アドレス 0x43 |
| アンテナ切替 | FM8625H。**電源は IO エキスパンダの P0**、送受の切替は SX1262 の DIO2 |
| 発振器 | TCXO、**3.0V、SX1262 の DIO3 から給電** |
| 電源 | JW5712 で 3.3V を生成。**入力は Cap-Bus の 5V 出力ピン** |

### 8.2 ピン【実測】

公式ドキュメント・ラベル・回路図のピン番号は Cardputer-ADV 用。CardputerZero での番号は次のとおり。

| 信号 | ADV 用（ラベル・回路図） | CardputerZero |
|---|---|---|
| RST | G3 | **GPIO26** |
| IRQ（DIO1） | G4 | **GPIO23** |
| BUSY | G6 | **GPIO22** |
| SCK | G40 | **GPIO11**（SPI0） |
| MOSI | G14 | **GPIO10**（SPI0） |
| MISO | G39 | **GPIO9**（SPI0） |
| NSS | G5 | **GPIO7**（SPI0 CE1、`/dev/spidev0.1`） |
| SDA／SCL | G8／G9 | **GPIO2／GPIO3**（I2C1） |
| GPS | G13／G15 | **GPIO14／GPIO15**（`/dev/serial0`） |

- すべて実機で確認済み。RST と BUSY はリセット時の挙動、IRQ は受信待ちのタイムアウト割り込み（0.5 秒の設定で 0.503 秒後に立ち上がり）で確かめた。

### 8.3 電源【実測】

- `/sys/class/leds/ext_5v_out/brightness` に 1 を書くと Cap に給電され、0 で切れる。`gpio` グループなら `sudo` 不要。
- 標準の GPS アプリは、起動時に 5V を入れ、終了時に切る。アプリを終了すると、I2C の 0x43 も消える。
- 自作アプリは、起動時に自分で 5V を入れる必要がある。

### 8.4 GPS【実測】

- 標準の GPS アプリで測位できた。
- 出力は `/dev/serial0`、115200bps。GPS、GLONASS、Galileo、BeiDou、みちびき（QZSS）の 5 つの衛星系を受信する。
- 標準アプリの実行中は `/dev/serial0` が専有され、ほかのプロセスからは開けない。
- 給電直後の出力に `$GPTXT,01,01,01,ANTENNA OPEN` が出る。【推定】回路図上、アンテナ端子に直流の負荷が無い構成のため出る通知で、異常ではない。

### 8.5 SX1262 の初期化と受信【実測】

リセット直後に読んだ値:

- 状態は待機（STBY_RC）。
- 識別文字列（レジスタ 0x0320）は「SX1261 V2D 2D02」。SX126x 系で共通の文字列で、SX1262 でもこの値が返る。
- LoRa の同期語レジスタ（0x0740）は既定値の 0x14 0x24。
- エラー情報は 0x0020（発振器の起動エラー）。TCXO の設定をする前だったため。設定後は 0x0000 になった。

受信までの手順（動作確認済み）:

1. 5V 出力を入れる。
2. IO エキスパンダ 0x43 の P0 を出力 High にする（レジスタ 0x05 の bit0＝1、0x03 の bit0＝1、0x07 の bit0＝0）。デバイス ID レジスタ 0x01 は 0xA2 だった。
3. GPIO26 でリセットする。
4. `SetStandby(RC)` → `SetDIO3AsTcxoCtrl(3.0V)` → `Calibrate` → `SetDIO2AsRfSwitchCtrl` → `SetRegulatorMode(DC-DC)`
5. LoRa の設定（周波数、`CalibrateImage`、変調、パケット、同期語）を書き、`SetRx` で受信に入る。

受信の結果（923.0MHz、125kHz 幅、SF9。Unit C6L に入れた自作ビーコンを室内の近距離で受信）:

| 状態 | 受信強度 | 信号対雑音比 |
|---|---|---|
| 遮蔽物なし | −73〜−79dBm | +9〜+11dB |
| 遮蔽物あり | −86〜−87dBm | −1〜+2dB |
| 無信号時 | 約 −90dBm | — |

- 10 分間で 7 通を受信。通番に欠けなし、誤り検査はすべて正常。
- Python（`spidev` と `gpiod`）だけで、`sudo` なし・追加パッケージなしで動いた。
- 送信の命令は一度も出していない。

---

## 9. Cap CC1101

### 9.1 構成

- CC1101（Sub-GHz、315／433／868／915MHz）と ST25R3916（NFC、13.56MHz）を 1 つの Cap に載せている。
- ラベルに、Cardputer-ADV・CardputerZero・P4 の機種別のピン表が印刷されている。
- I2C のデバイスは載っていない。【実測】

### 9.2 ピン【実測】

| 信号 | ADV 用 | CardputerZero | 確認 |
|---|---|---|---|
| CC1101 の CS | G5 | **GPIO7**（SPI0 CE1、`/dev/spidev0.1`） | 実機で応答 |
| ST25R3916 の CS | G6 | **GPIO22**（GPIO で手動制御） | 実機で応答 |
| SCK／MOSI／MISO | G40／G14／G39 | **GPIO11／10／9** | 実機で応答 |
| RF_SW0 | G13 | GPIO14 | ラベル記載、未検証 |
| GDO0 | G15 | GPIO15 | ラベル記載、未検証 |
| NFC_IRQ | G4 | GPIO23 | ラベル記載、未検証 |
| RST | G3 | GPIO26 | ラベル記載、未検証 |

識別の結果:

| チップ | SPI モード | 読んだ値 |
|---|---|---|
| CC1101 | モード 0 | PARTNUM 0x00、VERSION 0x14、状態 IDLE |
| ST25R3916 | モード 1 | IC Identity（レジスタ 0x3F）0x2A＝ST25R3916 のリビジョン 2 |

### 9.3 ハマりどころ【実測】

- **2 つのチップで SPI のモードが違う。** CC1101 はモード 0、ST25R3916 はモード 1。
- **ST25R3916 の CS は、SPI のハードウェア CS ではない。** `spidev` の `no_cs` を有効にして GPIO で制御し、その間 CC1101 が選ばれないようにする必要がある。
- **ラベルの小さい印字を写真から読むと、2 つの CS を取り違えやすい。** 実際に、CC1101 と NFC の CS を逆に読んだ。その前提で NFC 用の読み取り命令を送ったところ、CC1101 には書き込み命令として解釈され、送信用バッファに 1 バイト入った（送信開始の命令は出しておらず、電波は出ていない）。相手のチップを読み取り専用の命令で識別してから進めるべき。
- **5V 出力を切っても、CC1101 の内部状態が残っていた。** 完全な電源断になっていない可能性がある。初期化のときは必ずリセット命令（SRES）を出すのがよい。

---

## 10. 標準アプリの送信機能についての注意

- 標準で入っている LoRa アプリと SubG Chat アプリは、送信機能を持つ。
- これらのアプリが使う周波数と出力が、7 章の認証条件に収まっているかは、バイナリからは読み取れず未確認。
- 確認できるまでは、送信の操作は控えるのが無難。GPS アプリと NFC アプリには、この心配はない。

---

## 11. 調査結果を使って動かしたもの（参考）

調査で分かった仕組みが実際に使えることの確認として、自作の星座盤アプリを動かした。

- フレームバッファへ直接描画し、キーボードを入力デバイスから直接読む作りにした。依存は、最初から入っている Pillow と numpy だけ。
- `.deb` は実機上で組み立てた（`dpkg-deb` は本体に入っている）。登録ファイルとアイコンを所定の場所に置くと、ランチャーの一覧にアイコン付きで出た。
- メモリは UI 約 34MB、計算側約 21MB。
- 内蔵の地磁気センサと加速度センサで、本体の向きに合わせて星図を回す。較正後のずれは、水平でも傾けても 4〜5° 程度。

---

## 12. 記事化にあたっての注意

- **試験成績書の PDF には「複製禁止」の透かしがあり、全文以外の複製を認めない注記がある。** 写真や図をそのまま載せるのは避け、数値の引用と出典の明示にとどめるのが安全。総務省の検索結果の画面も、引用の範囲で扱う。
- **電波法に関する記述は、認証の記載内容という事実と、その解釈を分けて書く。** 解釈には「推定」と明記する。送信の可否を断定する書き方は避け、「専門家への確認を推奨」と添える。
- **数値はすべて 1 台・1 日の測定。** メモリや受信強度は、条件で変わる。
- 未確認の項目（下記）を、確認済みのように書かない。
- 自宅の位置が分かる情報（受信したビーコンの中身など）は載せない。

### 未確認の項目

- 標準の LoRa アプリと SubG Chat アプリの送信設定
- Cap CC1101 の RF_SW0、GDO0、NFC_IRQ、RST の各ピン
- CC1101 の 922MHz 帯「75mW」の制度上の位置づけ
- NFC（13.56MHz）の電波法上の扱い
- I2C の 0x4f のデバイスの正体
- 画面用メモリ 64MB での、動画撮影や長時間のカメラ使用
- 屋外での LoRa の到達距離
- Meshtastic のプリセット名と設定値の対応

### 手元にある素材

- Cap 2 種のラベルの写真（表と裏）
- 総務省の検索結果の画面（本体、Cap 2 種、C6L、PaperMono、CoreS3）
- 公式の電池試験のグラフ（Kickstarter Update #15）
- 星座盤を表示した本体の写真、本体から取得したスクリーンショット（320×170）

---

## 13. 出典

- [総務省 技術基準適合証明等を受けた機器の検索](https://www.tele.soumu.go.jp/giteki/SearchServlet?pageID=js01)（工事設計認証 020-260249、211-251216、219-269336、211-250603、211-260514、219-239073 と添付の試験成績書）
- [Kickstarter: CardputerZero Update #15「Shipping Progress, Battery Test Results & Software Updates」](https://www.kickstarter.com/projects/m5stack/cardputerzero/posts/4854427)（2026-11-10）
- [M5Stack Docs: CardputerZero 使用ガイド](https://docs.m5stack.com/en/compute/cardputerzero/usage)
- [M5Stack Docs: CardputerZero Image Burning Guide](https://docs.m5stack.com/en/compute/cardputerzero/image)
- [M5Stack Docs: Cap LoRa-1262](https://docs.m5stack.com/en/cap/Cap_LoRa-1262)
- [M5Stack Docs: Cap CC1101](https://docs.m5stack.com/en/cap/Cap_CC1101)
- [回路図: Cap LoRa-1262 V1.1](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1208/U214-sche-Cap-LoRa1262_SCH_V1.1_20251029_2025_11_07_22_53_19.pdf)
- [回路図: Stamp LoRa-1262 Mini](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1208/NEW-1262-SCH_A1-Lora_2025_08_27_10_58_52.pdf)
- [GitHub: CardputerZero/Camera のリリース](https://github.com/CardputerZero/Camera/releases)
- [GitHub: CardputerZero/m5stack-imager](https://github.com/CardputerZero/m5stack-imager)
- 実測の詳細な記録: リポジトリ [osprey74/cardputerzero-apps](https://github.com/osprey74/cardputerzero-apps) の `HANDOFF_cardputerzero.md` §1.3、§4.2.1、§9.1
