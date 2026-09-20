use crate::{clamp_boundary, save_layout, theme, OUTPUT, WIDTH};
use cxx_qt::{CxxQtType, Threading};
use cxx_qt_lib::QString;
use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use std::{
    pin::Pin,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

#[cxx_qt::bridge]
pub mod qobject {
    unsafe extern "C++" {
        include!("cxx-qt-lib/qstring.h");
        type QString = cxx_qt_lib::QString;
    }
    extern "RustQt" {
        #[qobject]
        #[qml_element]
        #[qproperty(i32, boundary, READ, NOTIFY)]
        #[qproperty(QString, theme_json, cxx_name = "themeJson")]
        #[qproperty(QString, status)]
        type Backend = super::BackendRust;

        #[qinvokable]
        #[cxx_name = "set_boundary"]
        fn change_boundary(self: Pin<&mut Self>, value: i32);
        #[qinvokable]
        fn reset(self: Pin<&mut Self>);
        #[qinvokable]
        fn save(self: Pin<&mut Self>);
        #[qinvokable]
        fn refresh_theme(self: Pin<&mut Self>);
        #[qinvokable]
        fn watch_theme(self: Pin<&mut Self>);
        #[qinvokable]
        fn report(self: Pin<&mut Self>, message: QString);
    }
    impl cxx_qt::Threading for Backend {}
}

pub struct BackendRust {
    boundary: i32,
    theme_json: QString,
    status: QString,
    watcher: Option<RecommendedWatcher>,
    refresh_queued: Arc<AtomicBool>,
}

impl Default for BackendRust {
    fn default() -> Self {
        Self {
            boundary: 1280,
            theme_json: QString::from(theme::read().to_string().as_str()),
            status: QString::from("Drag the shared edge or enter an exact width."),
            watcher: None,
            refresh_queued: Arc::new(AtomicBool::new(false)),
        }
    }
}

impl qobject::Backend {
    pub fn report(self: Pin<&mut Self>, message: QString) {
        println!("{message}");
    }
    pub fn change_boundary(mut self: Pin<&mut Self>, value: i32) {
        let boundary = clamp_boundary(value);
        if *self.boundary() != boundary {
            self.as_mut().rust_mut().boundary = boundary;
            self.as_mut().boundary_changed();
        }
        self.set_status(QString::from(
            format!(
                "Left {boundary} px · Right {} px · No overlap",
                WIDTH - boundary
            )
            .as_str(),
        ));
    }
    pub fn reset(self: Pin<&mut Self>) {
        self.change_boundary(1280);
    }
    pub fn save(self: Pin<&mut Self>) {
        let status = match OUTPUT.get().and_then(Option::as_ref) {
            Some(path) => match save_layout(path, *self.boundary()) {
                Ok(()) => format!("Saved test definitions: {}", path.display()),
                Err(e) => format!("Save failed: {e}"),
            },
            None => "Save disabled. Launch with --output /path/to/test-layout.conf.".into(),
        };
        self.set_status(QString::from(status.as_str()));
    }
    pub fn refresh_theme(mut self: Pin<&mut Self>) {
        self.rust().refresh_queued.store(false, Ordering::Relaxed);
        self.as_mut()
            .set_theme_json(QString::from(theme::read().to_string().as_str()));
        if let Some(watcher) = self.as_mut().rust_mut().watcher.as_mut() {
            // Reattach when the active theme symlink or directory has changed.
            let _ = watcher.watch(&theme::directory(), RecursiveMode::NonRecursive);
        }
    }
    pub fn watch_theme(mut self: Pin<&mut Self>) {
        if self.rust().watcher.is_some() {
            return;
        }
        let qt_thread = self.qt_thread();
        let queued = self.rust().refresh_queued.clone();
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
                    && qt_thread.queue(|object| object.refresh_theme()).is_err()
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
                    Ok(()) => self.as_mut().rust_mut().watcher = Some(watcher),
                    Err(e) => self.set_status(QString::from(
                        format!("Theme watcher unavailable: {e}").as_str(),
                    )),
                }
            }
            Err(e) => self.set_status(QString::from(
                format!("Theme watcher unavailable: {e}").as_str(),
            )),
        }
    }
}
