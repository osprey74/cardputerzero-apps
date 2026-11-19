#!/bin/sh
# LAN Scanner の起動ラッパー（APPLaunch の Exec）。ESC 長押しでランチャーが終了させる。
exec /usr/bin/python3 /usr/share/APPLaunch/lib/lan-scanner/src/lan_scanner.py "$@"