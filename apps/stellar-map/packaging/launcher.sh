#!/bin/sh
# Stellar Map ランチャー: フレームバッファ UI がサイドカー(Python)を子プロセス起動して Scene を描く。
# APPLaunch からはこのラッパーが起動される（APP_EXEC）。APPLaunch は外部アプリの実行中、
# 自身のキーボード処理を止めて待機し、ESC 長押しでアプリを終了させる。
LIB=/usr/share/APPLaunch/lib/stellar-map
export PYTHONPATH="$LIB:${PYTHONPATH:-}"
export STELLAR_SIDECAR="$LIB/sidecar/stellar_sidecar.py"
# フレーム間隔[秒]: 方位追従を滑らかにするため既定 0.25（STELLAR_INTERVAL で変更可）
exec /usr/bin/python3 "$LIB/ui_fb/stellar_fb.py" --interval "${STELLAR_INTERVAL:-0.25}" "$@"
