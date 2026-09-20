use serde_json::{json, Value};
use std::{env, fs, path::PathBuf, process::Command};

pub fn directory() -> PathBuf {
    let state = env::var_os("XDG_STATE_HOME")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env::var_os("HOME").unwrap_or_default()).join(".local/state")
        });
    state.join("omarchy/current/theme")
}

fn toml_file(name: &str) -> toml::Table {
    fs::read_to_string(directory().join(name))
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or_default()
}
fn text(table: &toml::Table, key: &str, fallback: &str) -> String {
    table
        .get(key)
        .and_then(toml::Value::as_str)
        .unwrap_or(fallback)
        .to_owned()
}
fn section_number(table: &toml::Table, section: &str, key: &str, fallback: f64) -> f64 {
    table
        .get(section)
        .and_then(|v| v.get(key))
        .and_then(|v| v.as_float().or_else(|| v.as_integer().map(|n| n as f64)))
        .unwrap_or(fallback)
}
fn option(name: &str) -> Option<Value> {
    // The only compositor calls in this PoC are read-only option queries.
    let output = Command::new("hyprctl")
        .args(["-j", "getoption", name])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    serde_json::from_slice(&output.stdout).ok()
}

pub fn parse_gradient(text: &str, fallback: &str) -> (String, String, f64) {
    let mut colors = Vec::new();
    let mut angle = 0.;
    for token in text.split_whitespace() {
        if let Some(degrees) = token
            .strip_suffix("deg")
            .and_then(|v| v.parse::<f64>().ok())
        {
            if degrees.is_finite() {
                angle = degrees;
            }
        } else if token.len() == 8 && token.chars().all(|c| c.is_ascii_hexdigit()) {
            // hyprctl serializes ARGB while rgba(...) configuration uses RGBA.
            colors.push(format!("#{}", &token[2..]));
        } else if let Some(value) = token
            .strip_prefix("rgba(")
            .and_then(|v| v.strip_suffix(')'))
        {
            if value.len() == 8 && value.chars().all(|c| c.is_ascii_hexdigit()) {
                colors.push(format!("#{}", &value[..6]));
            }
        } else if token.len() == 7 && token.starts_with('#') {
            colors.push(token.to_owned());
        }
    }
    let first = colors
        .first()
        .cloned()
        .unwrap_or_else(|| fallback.to_owned());
    let last = colors.last().cloned().unwrap_or_else(|| first.clone());
    (first, last, angle)
}

pub fn read() -> Value {
    let colors = toml_file("colors.toml");
    let shell = toml_file("shell.toml");
    let accent = text(&colors, "accent", "#67d4e8");
    let border_option = option("general:col.active_border");
    let gradient = border_option
        .as_ref()
        .and_then(|v| v["gradient"].as_str())
        .map(str::to_owned)
        .unwrap_or_else(|| text(&colors, "hyprland_active_border", &accent));
    let (start, end, angle) = parse_gradient(&gradient, &accent);
    let rounding = option("decoration:rounding")
        .and_then(|v| v["int"].as_i64())
        .unwrap_or(10)
        .clamp(0, 50);
    let border = option("general:border_size")
        .and_then(|v| v["int"].as_i64())
        .unwrap_or(2)
        .clamp(1, 8);
    json!({
        "background": text(&colors,"background","#0b1420"),
        "surface": text(&colors,"dark_background","#07101a"),
        "raised": text(&colors,"lighter_background","#132334"),
        "foreground": text(&colors,"foreground","#f4f7fa"),
        "muted": text(&colors,"muted","#70869c"), "accent": accent,
        "borderStart": start, "borderEnd": end, "borderAngle": angle,
        "borderWidth": border, "rounding": rounding,
        "fontSize": section_number(&shell,"font","base-size",12.).clamp(8.,32.),
        "controlFill": section_number(&shell,"controls","normal-fill-alpha",0.04).clamp(0.,1.),
        "controlBorder": section_number(&shell,"controls","normal-border-alpha",0.4).clamp(0.,1.),
        "hoverFill": section_number(&shell,"controls","hover-cursor-fill-alpha",0.08).clamp(0.,1.),
        "themeDirectory": directory(), "liveHyprland": border_option.is_some()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_live_and_theme_border_formats() {
        assert_eq!(
            parse_gradient("ff72f1ff ffffc857 45deg", "#000000"),
            ("#72f1ff".into(), "#ffc857".into(), 45.)
        );
        assert_eq!(
            parse_gradient("rgba(72f1ffff) rgba(ffc857ff)", "#000000"),
            ("#72f1ff".into(), "#ffc857".into(), 0.)
        );
    }
}
