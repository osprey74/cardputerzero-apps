#!/bin/sh
# Wi-Fi Analyzer の起動ラッパー（APPLaunch の Exec）。ESC 長押しでランチャーが終了させる。
exec /usr/bin/python3 /usr/share/APPLaunch/lib/wifi-analyzer/src/wifi_analyzer.py "$@"