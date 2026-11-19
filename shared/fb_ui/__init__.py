"""CardputerZero 用のフレームバッファ UI 共通部品（Python・Pillow＋numpy）。

標準ランチャーと同じく `/dev/fb0` へ直接描き、キーボードは evdev（tca8418c）を直接読む
（HANDOFF §4.2.1）。依存は工場出荷イメージに入っている Pillow と numpy のみ。
"""
from .fbui import (  # noqa: F401
    KEY,
    THEME,
    Display,
    Keyboard,
    common_args,
    font,
    footer,
    header,
    new_canvas,
    run,
    text_w,
    truncate,
)
