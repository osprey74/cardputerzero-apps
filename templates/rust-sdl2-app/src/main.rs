//! CardputerZero スタンドアロン SDL2 アプリ雛形（`legacy-deb-only`）。
//!
//! - **320×170 厳守**（CardputerZero LCD 実解像度）。ウィンドウは固定サイズ。
//! - 実機では SDL2 が LCD へ描画。開発機では 320×170 ウィンドウが開く。
//! - `CZ_SCREENSHOT=<path.bmp>` で 1 フレーム描いて BMP 保存し終了（ヘッドレス検証/CI 用）。
//!   併せて `SDL_VIDEODRIVER=offscreen` を指定すれば表示装置なしで描画できる。
//! - 通常実行時は SDL_Quit / Esc / SIGTERM で終了。
//!
//! ⚠️ ビルドに `libsdl2-dev` + `pkg-config`、実行に `libsdl2-2.0-0` が必要。

mod draw;
mod font8x8;

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use sdl2::event::Event;
use sdl2::keyboard::Keycode;
use sdl2::pixels::{Color, PixelFormatEnum};
use sdl2::render::WindowCanvas;

/// CardputerZero LCD 実解像度（厳守）。
const W: u32 = 320;
const H: u32 = 170;

static STOP: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(_sig: libc::c_int) {
    STOP.store(true, Ordering::SeqCst);
}

/// 1 フレーム描画（雛形デモ: 円＋十字＋色サンプル点＋テキスト）。
fn render(cv: &mut WindowCanvas) {
    cv.set_draw_color(Color::RGB(0x10, 0x14, 0x18)); // osprey74 ダーク背景
    cv.clear();

    // 左 170×170: 全天図を模した円＋十字（星座盤 UI と同じ座標系の例）
    draw::circle(cv, 85, 85, 80, [60, 66, 70]);
    draw::line(cv, (85, 6), (85, 164), [40, 50, 58]);
    draw::line(cv, (6, 85), (164, 85), [40, 50, 58]);

    // 色サンプルの点（1等星/2等星/惑星/DSO 相当の配色）
    let sample = [[255, 255, 255], [150, 220, 255], [255, 215, 120], [200, 120, 200]];
    for (i, c) in sample.iter().enumerate() {
        draw::fill_square(cv, 45 + i as i32 * 28, 85, 3, *c);
    }

    // 右 150px: テキスト（8×8 フォント）
    draw::text(cv, 176, 16, "Hello CZ", [0x4F, 0xC3, 0xF7], 2);
    draw::text(cv, 176, 42, "SDL2 template", [200, 200, 200], 1);
    draw::text(cv, 176, 56, "320x170 strict", [120, 140, 160], 1);
    draw::text(cv, 176, 140, "Esc: quit", [90, 100, 110], 1);

    cv.present();
}

/// Canvas の内容を BMP に保存（SDL 組込み・追加依存なし）。
fn save_bmp(cv: &mut WindowCanvas, path: &str) {
    let (w, h) = cv.output_size().expect("output_size");
    let mut data = cv
        .read_pixels(None, PixelFormatEnum::RGB24)
        .expect("read_pixels");
    let pitch = w * 3;
    let surf = sdl2::surface::Surface::from_data(&mut data, w, h, pitch, PixelFormatEnum::RGB24)
        .expect("surface");
    surf.save_bmp(path).expect("save_bmp");
    eprintln!("screenshot -> {path} ({w}x{h})");
}

fn main() {
    unsafe {
        libc::signal(libc::SIGTERM, on_signal as *const () as usize);
        libc::signal(libc::SIGINT, on_signal as *const () as usize);
    }

    let sdl = sdl2::init().expect("SDL init");
    let video = sdl.video().expect("SDL video");
    let window = video
        .window("cz-hello-sdl2", W, H)
        .position_centered()
        .build()
        .expect("window");
    let mut canvas = window.into_canvas().build().expect("canvas");

    // スクリーンショットモード: 1 フレームだけ描いて保存し終了
    if let Ok(path) = std::env::var("CZ_SCREENSHOT") {
        render(&mut canvas);
        save_bmp(&mut canvas, &path);
        return;
    }

    let mut events = sdl.event_pump().expect("event pump");
    while !STOP.load(Ordering::Relaxed) {
        for e in events.poll_iter() {
            match e {
                Event::Quit { .. }
                | Event::KeyDown {
                    keycode: Some(Keycode::Escape),
                    ..
                } => return,
                _ => {}
            }
        }
        render(&mut canvas);
        std::thread::sleep(Duration::from_millis(33)); // ~30fps
    }
}
