//! 320×170 低解像度 LCD 向けの最小描画ヘルパー（SDL2 Canvas 上）。
//!
//! HANDOFF §App16 決定に従い「四角ドット＋アンチエイリアス無し＋等倍」を基本とする
//! （低解像度では AA 無しの方が鮮明）。点は一辺 `side` px の塗り四角、文字は 8×8
//! ビットマップフォント（`font8x8`）を等倍/整数倍で描く。

use sdl2::pixels::Color;
use sdl2::rect::{Point, Rect};
use sdl2::render::WindowCanvas;

use crate::font8x8::FONT8X8;

#[inline]
pub fn rgb(c: [u8; 3]) -> Color {
    Color::RGB(c[0], c[1], c[2])
}

/// 中心 (cx,cy)・一辺 side の塗り四角（Scene の point プリミティブ）。
pub fn fill_square(cv: &mut WindowCanvas, cx: i32, cy: i32, side: i32, color: [u8; 3]) {
    let s = side.max(1);
    cv.set_draw_color(rgb(color));
    let _ = cv.fill_rect(Rect::new(cx - s / 2, cy - s / 2, s as u32, s as u32));
}

/// 直線（Scene の line プリミティブ）。
pub fn line(cv: &mut WindowCanvas, a: (i32, i32), b: (i32, i32), color: [u8; 3]) {
    cv.set_draw_color(rgb(color));
    let _ = cv.draw_line(Point::new(a.0, a.1), Point::new(b.0, b.1));
}

/// 円の輪郭（midpoint 法）。地平線円などに使う。
pub fn circle(cv: &mut WindowCanvas, cx: i32, cy: i32, r: i32, color: [u8; 3]) {
    cv.set_draw_color(rgb(color));
    let (mut x, mut y) = (r, 0);
    let mut err = 1 - r;
    while x >= y {
        for &(px, py) in &[
            (cx + x, cy + y), (cx + y, cy + x), (cx - y, cy + x), (cx - x, cy + y),
            (cx - x, cy - y), (cx - y, cy - x), (cx + y, cy - x), (cx + x, cy - y),
        ] {
            let _ = cv.draw_point(Point::new(px, py));
        }
        y += 1;
        if err < 0 {
            err += 2 * y + 1;
        } else {
            x -= 1;
            err += 2 * (y - x) + 1;
        }
    }
}

/// 8×8 ビットマップ文字列（scale 倍）。ビットは MSB=左。前進は 8*scale px。
pub fn text(cv: &mut WindowCanvas, x: i32, y: i32, s: &str, color: [u8; 3], scale: i32) {
    let sc = scale.max(1);
    cv.set_draw_color(rgb(color));
    let mut cx = x;
    for ch in s.chars() {
        let glyph = FONT8X8.get(ch as usize).copied().unwrap_or([0; 8]);
        for (row, bits) in glyph.iter().enumerate() {
            for col in 0..8i32 {
                // font8x8 は MSB=左（bit7 が左端）。
                if bits & (0x80 >> col) != 0 {
                    let px = cx + col * sc;
                    let py = y + row as i32 * sc;
                    let _ = cv.fill_rect(Rect::new(px, py, sc as u32, sc as u32));
                }
            }
        }
        cx += 8 * sc;
    }
}
