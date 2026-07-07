//! App 16 星座盤 UI (czdev/LVGL) ― サイドカーの Scene JSON を描く薄い front-end。
//!
//! アーキテクチャ: Python サイドカー (`sidecar/stellar_sidecar.py`) が天体計算・投影を行い、
//! 320×170 のデバイス座標プリミティブ (Scene) を JSON Lines で stdout に出す。本 UI は
//! 子プロセスとして起動し、1 行=1 フレームを読み、四角・線・文字を描くだけ。
//!
//! 状態: **scaffold**。プロセス連携と Scene パースは実装済み。LVGL 描画呼び出し (`draw_scene`)
//! は czdev(AppBuilder) 到着後に czdev API へ合わせて確定する TODO スタブ。czdev/実機が無いため
//! 本 crate はまだコンパイルしていない。
//!
//! 描画方針 (HANDOFF §App16 決定): 四角ドット＋AA 無し＋等倍が低解像度 LCD で最も鮮明。
//! points の side は四角の一辺 [px]、色は [r,g,b]。

// scaffold: 一部フィールドは LVGL 描画 (draw_scene) 実装時に使う。それまで未使用を許容。
#![allow(dead_code)]

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};

use serde::Deserialize;

/// サイドカーが吐く 1 フレーム (Scene)。座標は 320×170 の整数デバイス画素。
#[derive(Debug, Deserialize)]
struct Scene {
    w: i32,
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
    phase: String,
}

#[derive(Debug, Deserialize)]
struct Counts {
    stars: i32,
    lines: i32,
    dso: i32,
    planets: i32,
}

/// 1 フレームを LCD に描く。
///
/// TODO(czdev): 以下を czdev/LVGL の描画 API に置き換える。到着後に確定。
///   - 画面クリア (黒)
///   - chrome.circle を円で、十字線、dirs を文字で (dir_color)
///   - lines を線で (line_color)
///   - points を「一辺 side の塗り四角」で (中心 x,y・色 r,g,b)。AA 無し・等倍。
///   - labels を小フォント文字で
///   - 右 150px に meta から情報パネル (time/lat/lon/counts/moon)
/// LVGL では points は lv_canvas_set_px か lv_draw_rect(塗り) が候補。文字は 1bpp ビットマップフォント。
fn draw_scene(scene: &Scene) {
    // --- scaffold: 実描画の代わりにフレーム要約をログ出力（配線の確認用） ---
    let m = &scene.meta;
    let moon = m
        .moon
        .as_ref()
        .map(|mo| {
            format!(
                "{:.0}% {} {}",
                mo.frac * 100.0,
                if mo.waxing { "wax" } else { "wan" },
                mo.phase
            )
        })
        .unwrap_or_else(|| "-".into());
    eprintln!(
        "[frame] {} lat={:.2} lon={:.2} {}x{} | stars={} lines={} dso={} planets={} | points={} labels={} | moon={}",
        m.time_local, m.lat, m.lon, scene.w, scene.h,
        m.counts.stars, m.counts.lines, m.counts.dso, m.counts.planets,
        scene.points.len(), scene.labels.len(), moon,
    );
    // 描画順の目安 (czdev API 確定後に実装):
    //   clear(); draw_circle(chrome.circle, chrome.circle_color); draw_cross();
    //   for d in &chrome.dirs { draw_text(d.0, d.1, &d.2, chrome.dir_color); }
    //   for l in &scene.lines { draw_line(l, scene.line_color); }
    //   for p in &scene.points { fill_square(p.0, p.1, p.2, [p.3,p.4,p.5]); }
    //   for t in &scene.labels { draw_text(t.0, t.1, &t.2, [t.3,t.4,t.5]); }
    //   draw_panel(&scene.meta);
    let _ = (&scene.chrome, &scene.lines, &scene.line_color, &scene.points, &scene.labels);
}

fn main() -> std::io::Result<()> {
    // サイドカーを起動し、Scene JSON Lines を読み続ける (デバイスでは 30s 毎に更新)。
    // 引数は実機で GNSS/RTC 連携に置き換える。ここでは既定 (現在時刻・札幌) を使う。
    let mut child = Command::new("python3")
        .arg("../sidecar/stellar_sidecar.py")
        .arg("--interval")
        .arg("30")
        .stdout(Stdio::piped())
        .spawn()?;

    let stdout = child
        .stdout
        .take()
        .expect("sidecar stdout を取得できません");
    let reader = BufReader::new(stdout);

    for line in reader.lines() {
        let line = line?;
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        match serde_json::from_str::<Scene>(&line) {
            Ok(scene) => draw_scene(&scene),
            Err(e) => eprintln!("[warn] Scene パース失敗: {e}"),
        }
    }
    Ok(())
}
