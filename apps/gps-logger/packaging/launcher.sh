#!/bin/sh
# GPS Logger の起動ラッパー（APPLaunch の Exec）。ESC 長押しでランチャーが SIGTERM を送ると、
# 記録中の GPX を閉じ、GPS の 5V 出力と画面の明るさを元に戻してから終了する。
exec /usr/bin/python3 /usr/share/APPLaunch/lib/gps-logger/src/gps_logger.py "$@"