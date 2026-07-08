//! App 16 星座盤 UI (SDL2) ― サイドカーの Scene JSON を 320×170 に描く薄い front-end。
//!
//! アーキテクチャ: Python サイドカー (`sidecar/stellar_sidecar.py`) が天体計算・投影を行い、
//! 320×170 のデバイス座標プリミティブ (Scene) を JSON Lines で吐く。本 UI はそれを読み、
//! 円・線・四角(点)・文字を描くだけ（HANDOFF §2.7.6【確定】= legacy-deb-only スタンドアロン
//! ネイティブバイナリ、SDL2 直描画）。描画は AA 無し・等倍（低解像度 LCD で最も鮮明）。
//!
//! フレーム入力:
//!   - 既定: サイドカーを子プロセス起動（`STELLAR_SIDECAR` で .py パス上書き可）。
//!   - `STELLAR_FROM_STDIN=1`: stdin から JSON Lines を読む（`sidecar.py | stellar-map`）。
//! 検証: `SDL_VIDEODRIVER=dummy CZ_SCREENSHOT=out.bmp` で 1 フレーム描いて BMP 保存し終了。

mod draw;
mod font8x8;

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};

use sdl2::pixels::{Color, PixelFormatEnum};
use sdl2::render::WindowCanvas;
use serde::Deserialize;

const W: u32 = 320;
const H: u32 = 170;

static STOP: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(_sig: libc::c_int) {
    STOP.store(true, Ordering::SeqCst);
}

/// サイドカーが吐く 1 フレーム (Scene)。座標は 320×170 の整数デバイス画素。
#[derive(Debug, Deserialize)]
struct Scene {
    #[allow(dead_code)]
    w: i32,
    #[allow(dead_code)]
    h: i32,
    chrome: Chrome,
    #[serde(default)]
    lines: Vec<(i32, i32, i32, i32)>,
    line_color: [u8; 3],
    /// (x, y, side, r, g, b)。配列順に描く (DSO→星→惑星→月)。
    #[serde(default)]
    points: Vec<(i32, i32, i32, u8, u8, u8)>,
    /// (x, y, text, r, g, b)。
    #[serde(default)]
    labels: Vec<(i32, i32, String, u8, u8, u8)>,
    meta: Meta,
}

#[derive(Debug, Deserialize)]
struct Chrome {
    /// (cx, cy, r)。
    circle: (i32, i32, i32),
    circle_color: [u8; 3],
    dir_color: [u8; 3],
    /// (x, y, "N"|"E"|"S"|"W")。
    dirs: Vec<(i32, i32, String)>,
}

#[derive(Debug, Deserialize)]
struct Meta {
    time_local: String,
    lat: f64,
    lon: f64,
    moon: Option<Moon>,
    counts: Counts,
}

#[derive(Debug, Deserialize)]
struct Moon {
    frac: f64,
    waxing: bool,
    #[allow(dead_code)]
    phase: String,
}

#[derive(Debug, Deserialize)]
struct Counts {
    stars: i32,
    lines: i32,
    dso: i32,
    planets: i32,
}

/// 右 150px の情報パネル（meta から）。
fn draw_panel(cv: &mut WindowCanvas, m: &Meta) {
    let x = 174;
    let mut y = 6;
    let c = [150, 170, 190];
    let dim = [110, 125, 140];
    draw::text(cv, x, y, "STELLAR MAP", [0x4F, 0xC3, 0xF7], 1);
    y += 14;
    draw::text(cv, x, y, &m.time_local, c, 1);
    y += 11;
    draw::text(cv, x, y, &format!("{:.2},{:.2}", m.lat, m.lon), c, 1);
    y += 14;
    draw::text(cv, x, y, &format!("stars={}", m.counts.stars), dim, 1);
    y += 10;
    draw::text(cv, x, y, &format!("lines={}", m.counts.lines), dim, 1);
    y += 10;
    draw::text(cv, x, y, &format!("dso={} pl={}", m.counts.dso, m.counts.planets), dim, 1);
    y += 14;
    if let Some(mo) = &m.moon {
        draw::text(cv, x, y, &format!("moon {:.0}%", mo.frac * 100.0), [225, 225, 205], 1);
        y += 10;
        draw::text(cv, x, y, if mo.waxing { "waxing" } else { "waning" }, dim, 1);
    }
}

/// 1 フレームを 320×170 に描く。
fn draw_scene(cv: &mut WindowCanvas, s: &Scene) {
    cv.set_draw_color(Color::RGB(0, 0, 0));
    cv.clear();

    // chrome: 地平線円＋十字（circle_color）
    let (cx, cy, r) = s.chrome.circle;
    draw::circle(cv, cx, cy, r, s.chrome.circle_color);
    draw::line(cv, (cx, cy - r), (cx, cy + r), s.chrome.circle_color);
    draw::line(cv, (cx - r, cy), (cx + r, cy), s.chrome.circle_color);

    // 星座線
    for l in &s.lines {
        draw::line(cv, (l.0, l.1), (l.2, l.3), s.line_color);
    }
    // 点（恒星/DSO/惑星/月）= 一辺 side の塗り四角
    for p in &s.points {
        draw::fill_square(cv, p.0, p.1, p.2, [p.3, p.4, p.5]);
    }
    // 天体ラベル
    for t in &s.labels {
        draw::text(cv, t.0, t.1, &t.2, [t.3, t.4, t.5], 1);
    }
    // 方位（N/E/S/W）
    for d in &s.chrome.dirs {
        draw::text(cv, d.0, d.1, &d.2, s.chrome.dir_color, 1);
    }
    // 情報パネル
    draw_panel(cv, &s.meta);

    cv.present();
}

fn save_bmp(cv: &mut WindowCanvas, path: &str) {
    let (w, h) = cv.output_size().expect("output_size");
    let mut data = cv.read_pixels(None, PixelFormatEnum::RGB24).expect("read_pixels");
    let surf = sdl2::surface::Surface::from_data(&mut data, w, h, w * 3, PixelFormatEnum::RGB24)
        .expect("surface");
    surf.save_bmp(path).expect("save_bmp");
    eprintln!("screenshot -> {path} ({w}x{h})");
}

/// reader から JSON Lines を読み、各 Scene を描く。screenshot 指定時は 1 フレームで終了。
fn run<R: BufRead>(mut reader: R, cv: &mut WindowCanvas, screenshot: Option<&str>) {
    let mut line = String::new();
    while !STOP.load(Ordering::Relaxed) {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => break, // EOF
            Ok(_) => {}
            Err(e) => {
                eprintln!("[warn] read: {e}");
                break;
            }
        }
        let t = line.trim();
        if t.is_empty() || t.starts_with('#') {
            continue;
        }
        match serde_json::from_str::<Scene>(t) {
            Ok(scene) => {
                draw_scene(cv, &scene);
                if let Some(path) = screenshot {
                    save_bmp(cv, path);
                    return;
                }
            }
            Err(e) => eprintln!("[warn] Scene パース失敗: {e}"),
        }
    }
}

fn main() -> std::io::Result<()> {
    unsafe {
        libc::signal(libc::SIGTERM, on_signal as *const () as usize);
        libc::signal(libc::SIGINT, on_signal as *const () as usize);
    }

    let sdl = sdl2::init().expect("SDL init");
    let video = sdl.video().expect("SDL video");
    let window = video
        .window("stellar-map", W, H)
        .position_centered()
        .build()
        .expect("window");
    let mut canvas = window.into_canvas().build().expect("canvas");

    let screenshot = std::env::var("CZ_SCREENSHOT").ok();

    if std::env::var("STELLAR_FROM_STDIN").is_ok() {
        // sidecar.py | stellar-map
        let stdin = std::io::stdin();
        run(stdin.lock(), &mut canvas, screenshot.as_deref());
        return Ok(());
    }

    // サイドカーを子プロセス起動して Scene を読む。
    let sidecar = std::env::var("STELLAR_SIDECAR")
        .unwrap_or_else(|_| "../sidecar/stellar_sidecar.py".to_string());
    let mut cmd = Command::new("python3");
    cmd.arg(&sidecar);
    if screenshot.is_none() {
        cmd.arg("--interval").arg("30"); // 常駐時は 30s 毎に更新（スクショ時は 1 発）
    }
    let mut child = cmd.stdout(Stdio::piped()).spawn()?;
    let stdout = child.stdout.take().expect("sidecar stdout");
    run(BufReader::new(stdout), &mut canvas, screenshot.as_deref());
    let _ = child.kill();
    Ok(())
}
