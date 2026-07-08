//! CardputerZero スタンドアロン framebuffer アプリ雛形（`legacy-deb-only`）。
//!
//! - `/dev/fb0` を直接描画。X / Wayland / LVGL ホスト不要の自己完結ネイティブバイナリ。
//! - APPLaunch は起動時に環境変数 `APPLAUNCH_LINUX_FBDEV_DEVICE` で fbdev を指定してくる
//!   （AppBuilder のコミット `use APPLAUNCH_LINUX_FBDEV_DEVICE ... instead of hardcoded /dev/fb0` 参照）。
//!   未設定時は `/dev/fb0` にフォールバック。
//! - SIGTERM / SIGINT を受けたら画面を消して終了（APPLaunch は SIGTERM を送る想定）。
//!
//! ⚠️ 本雛形は Windows 開発機ではビルド不可（framebuffer は Linux 専用）。
//!    実機（到着まで uConsole / aarch64 Linux）でネイティブビルド・検証すること。

use framebuffer::Framebuffer;
use std::sync::atomic::{AtomicBool, Ordering};

/// 終了要求フラグ（シグナルハンドラから立てる）。
static STOP: AtomicBool = AtomicBool::new(false);

/// osprey74 テーマ色（暫定・`shared/ui_theme` 整備後に同期する）。
const BG: (u8, u8, u8) = (0x10, 0x14, 0x18); // 背景（ダーク）
const ACCENT: (u8, u8, u8) = (0x4F, 0xC3, 0xF7); // アクセント（動作確認用の帯）

extern "C" fn on_signal(_sig: libc::c_int) {
    STOP.store(true, Ordering::SeqCst);
}

/// RGB を fbdev の bpp に合わせてパック（16bpp RGB565 / 32bpp BGRX に対応）。
fn pack(bpp: u32, (r, g, b): (u8, u8, u8)) -> [u8; 4] {
    match bpp {
        16 => {
            let v = ((r as u16 & 0xF8) << 8) | ((g as u16 & 0xFC) << 3) | (b as u16 >> 3);
            [(v & 0xFF) as u8, (v >> 8) as u8, 0, 0] // little-endian
        }
        _ => [b, g, r, 0xFF], // 32bpp は BGRX/BGRA が一般的
    }
}

/// フレーム全体を単色で塗る。
fn fill(frame: &mut [u8], line: u32, w: u32, y0: u32, y1: u32, bytes: usize, px: &[u8; 4]) {
    for y in y0..y1 {
        for x in 0..w {
            let off = (y * line) as usize + x as usize * bytes;
            frame[off..off + bytes].copy_from_slice(&px[..bytes]);
        }
    }
}

fn main() {
    // SIGTERM / SIGINT を捕捉
    unsafe {
        libc::signal(libc::SIGTERM, on_signal as *const () as usize);
        libc::signal(libc::SIGINT, on_signal as *const () as usize);
    }

    let path = std::env::var("APPLAUNCH_LINUX_FBDEV_DEVICE")
        .unwrap_or_else(|_| "/dev/fb0".to_string());

    let mut fb = match Framebuffer::new(&path) {
        Ok(fb) => fb,
        Err(e) => {
            eprintln!("framebuffer open failed ({path}): {e:?}");
            std::process::exit(1);
        }
    };

    let w = fb.var_screen_info.xres;
    let h = fb.var_screen_info.yres;
    let line = fb.fix_screen_info.line_length;
    let bpp = fb.var_screen_info.bits_per_pixel;
    let bytes = (bpp / 8) as usize;
    eprintln!("fbdev {path}: {w}x{h} {bpp}bpp line={line}");

    let bg = pack(bpp, BG);
    let ac = pack(bpp, ACCENT);
    let black = pack(bpp, (0, 0, 0));

    let mut frame = vec![0u8; (line * h) as usize];

    // 背景 + 中央にアクセント帯（"型"の描画動作確認）
    fill(&mut frame, line, w, 0, h, bytes, &bg);
    let band = h / 6;
    let y0 = h / 2 - band / 2;
    fill(&mut frame, line, w, y0, y0 + band, bytes, &ac);
    fb.write_frame(&frame);

    // 終了シグナルまで待機（5Hz で軽くポーリング）
    while !STOP.load(Ordering::Relaxed) {
        std::thread::sleep(std::time::Duration::from_millis(200));
    }

    // 後始末: 画面を黒に戻して終了（次アプリのため）
    fill(&mut frame, line, w, 0, h, bytes, &black);
    fb.write_frame(&frame);
}
