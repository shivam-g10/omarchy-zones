mod backend;
mod theme;

use cxx_qt_lib::{
    QGuiApplication, QMap, QMapPair_QString_QVariant, QQmlApplicationEngine, QString, QUrl,
    QVariant,
};
use serde_json::json;
use std::{
    env, fs,
    io::Write,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, OnceLock,
    },
};

const WIDTH: i32 = 2560;
const HEIGHT: i32 = 1414;
const MIN_WIDTH: i32 = 320;
static OUTPUT: OnceLock<Option<PathBuf>> = OnceLock::new();

fn clamp_boundary(value: i32) -> i32 {
    value.clamp(MIN_WIDTH, WIDTH - MIN_WIDTH)
}
fn definitions(boundary: i32) -> String {
    let boundary = clamp_boundary(boundary);
    format!(
        "omarchy-zones-v2\nprofile \"CXX-Qt PoC\"\nPOC-DISPLAY 0 0 {boundary} {HEIGHT}\nPOC-DISPLAY {boundary} 0 {} {HEIGHT}\n",
        WIDTH - boundary
    )
}
fn resolved(path: &Path) -> Result<PathBuf, String> {
    let full = if path.is_absolute() {
        path.to_owned()
    } else {
        env::current_dir().map_err(|e| e.to_string())?.join(path)
    };
    let parent = full
        .parent()
        .ok_or("Output needs a parent directory")?
        .canonicalize()
        .map_err(|e| format!("Output directory must exist: {e}"))?;
    Ok(parent.join(full.file_name().ok_or("Output needs a filename")?))
}
fn safe_output(path: &Path) -> Result<PathBuf, String> {
    let path = resolved(path)?;
    if fs::symlink_metadata(&path).is_ok_and(|m| m.file_type().is_symlink()) {
        return Err("Output cannot be a symlink".into());
    }
    let home = PathBuf::from(env::var_os("HOME").unwrap_or_default());
    let config = env::var_os("XDG_CONFIG_HOME")
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".config"));
    for production in [
        home.join(".config/omarchy-zones/zones.conf"),
        config.join("omarchy-zones/zones.conf"),
    ] {
        if path == production
            || resolved(&production).is_ok_and(|p| p == path)
            || production.canonicalize().is_ok_and(|p| p == path)
        {
            return Err("The PoC refuses to overwrite production zones.conf".into());
        }
    }
    Ok(path)
}
fn save_layout(path: &Path, boundary: i32) -> Result<(), String> {
    let path = safe_output(path)?;
    let temporary = path.with_file_name(format!(".cxxqt-poc-{}.tmp", std::process::id()));
    let mut created = false;
    let result = (|| -> std::io::Result<()> {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        created = true;
        file.write_all(definitions(boundary).as_bytes())?;
        file.sync_all()?;
        fs::rename(&temporary, &path)
    })();
    if result.is_err() && created {
        let _ = fs::remove_file(&temporary);
    }
    result.map_err(|e| e.to_string())
}

fn run() -> Result<i32, String> {
    let mut args = env::args().skip(1);
    let mut output = None;
    let mut probe = false;
    let mut smoke = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--output" => {
                output = Some(safe_output(Path::new(
                    &args.next().ok_or("--output requires a filename")?,
                ))?)
            }
            "--probe" => probe = true,
            "--smoke" => smoke = true,
            "--help" => {
                println!("zones-cxxqt-evaluation [--output TEST_FILE] [--probe | --smoke]\nNo default writes. Production zones.conf is rejected.");
                return Ok(0);
            }
            _ => return Err(format!("Unknown option: {arg}")),
        }
    }
    OUTPUT
        .set(output.clone())
        .map_err(|_| "Configuration was initialized twice")?;
    if probe {
        println!(
            "{}",
            json!({"bridge":"CXX-Qt 0.10.0", "theme":theme::read(), "width":WIDTH, "height":HEIGHT, "boundary":1280, "output":output})
        );
        return Ok(0);
    }
    let mut application = QGuiApplication::new();
    let app = application
        .as_mut()
        .ok_or("Failed to create QGuiApplication")?;
    app.set_application_name(&QString::from("zones-cxxqt-evaluation"));
    QGuiApplication::set_desktop_file_name(&QString::from("zones-cxxqt-evaluation"));
    let mut engine = QQmlApplicationEngine::new();
    let mut engine_ref = engine
        .as_mut()
        .ok_or("Failed to create QQmlApplicationEngine")?;
    let failed = Arc::new(AtomicBool::new(false));
    let failure_flag = failed.clone();
    engine_ref
        .as_mut()
        .on_object_creation_failed(move |_, url| {
            eprintln!("QML object creation failed: {url:?}");
            failure_flag.store(true, Ordering::Relaxed);
        })
        .release();
    let mut initial = QMap::<QMapPair_QString_QVariant>::default();
    initial.insert(QString::from("probeMode"), QVariant::from(&smoke));
    engine_ref.as_mut().set_initial_properties(&initial);
    engine_ref.load(&QUrl::from("qrc:/qt/qml/ZonesEvaluation/qml/Main.qml"));
    if failed.load(Ordering::Relaxed) {
        return Err("Failed to load QML".into());
    }
    Ok(application
        .as_mut()
        .ok_or("Application disappeared")?
        .exec())
}

fn main() {
    match run() {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn boundary_keeps_neighbors_contiguous_and_in_bounds() {
        for input in [i32::MIN, 0, 319, 320, 1280, 2240, 2560, i32::MAX] {
            let b = clamp_boundary(input);
            assert!((320..=2240).contains(&b));
            assert_eq!(b + (WIDTH - b), WIDTH);
            assert_eq!(definitions(input).lines().count(), 4);
        }
    }
}
