#!/bin/sh
# Stellar Map ランチャー: SDL2 UI がサイドカー(Python)を子プロセス起動して Scene を描く。
# APPLaunch からはこのラッパーが起動される（APP_EXEC）。
LIB=/usr/share/APPLaunch/lib/stellar-map
export PYTHONPATH="$LIB:${PYTHONPATH:-}"
export STELLAR_SIDECAR="$LIB/sidecar/stellar_sidecar.py"
exec "$LIB/stellar-map" "$@"
