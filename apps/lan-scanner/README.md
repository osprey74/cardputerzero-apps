# App11 LAN Scanner（`lan-scanner`）

CardputerZero がつながっているネットワーク（Wi-Fi・有線 LAN）の機器を探し、
IP・MAC・メーカー・名前を一覧にするアプリです。選んだ機器の開いている TCP ポートも調べられます。
画面は 320×170 のフレームバッファへ直接描きます（Python・Pillow＋numpy）。

> ⚠️ 自分が管理しているネットワークだけで使ってください。他人のネットワークの走査は、
> 管理者の許可が無ければ不正アクセスを疑われるおそれがあります。

## 画面の流れ

1. **開始**: 接続中のインターフェース（`wlan0`／`eth0`）と、走査する範囲を表示します。同じネットワークの前回の結果があれば、その日時と台数も出します。
2. **走査中**: ICMP → ARP → 名前 → 保存 の順に進みます（自宅の /24 で約 15 秒）。
3. **一覧**: IP・名前（mDNS／DNS が無ければメーカー名）。`GW`＝ゲートウェイ、`自分`＝本機、`(ARP)`＝ICMP に応えず ARP だけで見つかった機器、`●`＝前回は無かった機器、右端の `3p`＝開いているポート数。
4. **詳細**: MAC・メーカー・mDNS 名・DNS 名・応答時間。Enter で主要 27 ポート、A で 1〜1024 番を確認します。

## キー操作

| キー | 動作 |
|---|---|
| F／X（↑↓） | 選択（詳細画面では前後の機器へ）。Fn なしの単独押しでも動く |
| Enter | 走査開始／詳細を開く／主要ポートを確認 |
| A | 詳細画面で 1〜1024 番のポートを確認 |
| R | 再走査（開始画面ではインターフェースの再読込） |
| Esc | 戻る（走査中・ポート確認中は中止。長押しはランチャーが終了させる） |
| S | 画面を PNG で保存（`~/lan_shots/`） |
| Q | 終了 |

## 仕組み

nmap・arp-scan・avahi は工場出荷イメージに無いため、Python の標準ライブラリだけで作っています。root も不要です。

| 処理 | 方法 |
|---|---|
| 対象 | 本機がつながっているサブネット。/22 より広いときは本機を含む /24 に絞る |
| 発見 | ICMP エコーを 2 周（ping ソケット。`net.ipv4.ping_group_range` で一般ユーザーに許可されている）。送信で埋まった ARP 表（`ip -j neigh`）も読むので、ICMP に応えない機器も見つかる |
| 名前 | 逆引き DNS と、mDNS（224.0.0.251）への逆引き PTR の問い合わせ |
| メーカー | IEEE の OUI 一覧（`data/oui.tsv.gz`）。ローカル管理ビットが立った MAC は「ランダム化 MAC」と表示 |
| ポート | TCP の接続確認だけ（つながったらすぐ閉じる）。バナー取得・OS 推定・SYN スキャンはしない |
| 保存 | `~/lan_scans/scan_<日時>.json` と `.csv`。ポートを調べると同じファイルを更新する |
| 差分 | 同じネットワークの直前の結果と MAC（無ければ IP）で照合 |

OUI 表の更新:

```bash
python3 tools/build_oui.py          # https://standards-oui.ieee.org/oui/oui.csv から生成
```

## 動作確認（実機の SSH）

```bash
python3 src/lan_scanner.py --headless --auto --out-dir /tmp/lan_scans \
  --script "25 shot /tmp/list.png; 25.5 enter; 26 enter; 32 shot /tmp/detail.png; 33 quit"
python3 -m unittest discover -s tests     # ネットワークに触れない部分のテスト（PC でも動く）
```

## パッケージ

```bash
bash scripts/pack_deb.sh apps/lan-scanner        # 実機上で実行（dpkg-deb が必要）
apt-get -s install ./apps/lan-scanner/dist-cz/*.deb
sudo apt install ./apps/lan-scanner/dist-cz/*.deb
```

依存は工場出荷イメージに入っている `python3`・`python3-pil`・`python3-numpy`・`iproute2` だけです。
