mod theme;
use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use qtbridge::{QApp, QObjectHolder, qobject};
use serde_json::json;
use std::{
    env, fs,
    io::Write,
    path::{Path, PathBuf},
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, Ordering},
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
        "omarchy-zones-v2\nprofile \"Qt Bridges PoC\"\nPOC-DISPLAY 0 0 {boundary} {HEIGHT}\nPOC-DISPLAY {boundary} 0 {} {HEIGHT}\n",
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
    let temporary = path.with_file_name(format!(".qtbridge-poc-{}.tmp", std::process::id()));
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

pub struct Backend {
    boundary: i32,
    theme_json: String,
    status: String,
    watcher: Option<RecommendedWatcher>,
    refresh_queued: Arc<AtomicBool>,
}
impl Default for Backend {
    fn default() -> Self {
        Self {
            boundary: 1280,
            theme_json: theme::read().to_string(),
            status: "Drag the shared edge or enter an exact width.".into(),
            watcher: None,
            refresh_queued: Arc::new(AtomicBool::new(false)),
        }
    }
}
#[qobject]
impl Backend {
    qproperty!("boundary", Read = boundary, Notify = boundary_changed);
    qproperty!("themeJson", Read = theme_json, Notify = theme_changed);
    qproperty!("status", Read = status, Notify = status_changed);
    pub fn boundary(&self) -> i32 {
        self.boundary
    }
    pub fn theme_json(&self) -> String {
        self.theme_json.clone()
    }
    pub fn status(&self) -> String {
        self.status.clone()
    }
    #[qsignal]
    fn boundary_changed(&mut self);
    #[qsignal]
    fn theme_changed(&mut self);
    #[qsignal]
    fn status_changed(&mut self);
    #[qslot]
    pub fn set_boundary(&mut self, value: i32) {
        let next = clamp_boundary(value);
        if next != self.boundary {
            self.boundary = next;
            self.boundary_changed();
        }
        self.status = format!(
            "Left {} px · Right {} px · No overlap",
            self.boundary,
            WIDTH - self.boundary
        );
        self.status_changed();
    }
    #[qslot]
    pub fn reset(&mut self) {
        self.set_boundary(1280);
    }
    #[qslot]
    pub fn report(&self, message: String) {
        println!("{message}");
    }
    #[qslot]
    pub fn save(&mut self) {
        self.status = match OUTPUT.get().and_then(Option::as_ref) {
            Some(path) => match save_layout(path, self.boundary) {
                Ok(()) => format!("Saved test definitions: {}", path.display()),
                Err(e) => format!("Save failed: {e}"),
            },
            None => "Save disabled. Launch with --output /path/to/test-layout.conf.".into(),
        };
        self.status_changed();
    }
    #[qslot]
    pub fn refresh_theme(&mut self) {
        self.refresh_queued.store(false, Ordering::Relaxed);
        self.theme_json = theme::read().to_string();
        if let Some(watcher) = self.watcher.as_mut() {
            // Reattach if the active theme symlink or directory was replaced.
            let _ = watcher.watch(&theme::directory(), RecursiveMode::NonRecursive);
        }
        self.theme_changed();
    }
    #[qslot]
    pub fn watch_theme(&mut self) {
        if self.watcher.is_some() {
            return;
        }
        let invoker = self.get_qml_method_invoker();
        let queued = self.refresh_queued.clone();
        let callback = move |result: notify::Result<notify::Event>| {
            if let Ok(event) = result {
                if event.kind.is_access() {
                    return;
                }
                let relevant = event.paths.iter().any(|p| {
                    p.file_name()
                        .is_some_and(|n| n == "colors.toml" || n == "shell.toml" || n == "theme")
                });
                if relevant
                    && !queued.swap(true, Ordering::Relaxed)
                    && !invoker.invoke_method("refresh_theme")
                {
                    queued.store(false, Ordering::Relaxed);
                }
            }
        };
        match notify::recommended_watcher(callback) {
            Ok(mut watcher) => {
                let dir = theme::directory();
                if let Some(parent) = dir.parent() {
                    let _ = watcher.watch(parent, RecursiveMode::NonRecursive);
                }
                match watcher.watch(&dir, RecursiveMode::NonRecursive) {
                    Ok(()) => self.watcher = Some(watcher),
                    Err(e) => {
                        self.status = format!("Theme watcher unavailable: {e}");
                        self.status_changed();
                    }
                }
            }
            Err(e) => {
                self.status = format!("Theme watcher unavailable: {e}");
                self.status_changed();
            }
        }
    }
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
                println!(
                    "zones-qtbridge-poc [--output TEST_FILE] [--probe | --smoke]\nNo default writes. Never point it at production configuration."
                );
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
            json!({"bridge":"qtbridge 0.2.0","theme":theme::read(),"width":WIDTH,"height":HEIGHT,"boundary":1280,"output":output})
        );
        return Ok(0);
    }
    let mut app = QApp::new();
    Ok(app
        .application_name("omarchy-zones-qtbridge-poc")
        .register::<Backend>()
        .add_initial_property("probeMode", &smoke.into())
        .load_qml(include_bytes!("Main.qml"))
        .run())
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
