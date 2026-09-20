use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=adapter.cpp");
    println!("cargo:rerun-if-changed=bridge.h");
    let flags = Command::new("pkg-config")
        .args(["--cflags", "hyprland"])
        .output()
        .expect("pkg-config is required");
    assert!(
        flags.status.success(),
        "matching Hyprland headers are required"
    );
    let mut build = cc::Build::new();
    build
        .cpp(true)
        .std("c++23")
        .pic(true)
        .file("adapter.cpp")
        .flag("-fno-gnu-unique")
        .flag("-Wno-unused-parameter");
    for flag in String::from_utf8(flags.stdout).unwrap().split_whitespace() {
        build.flag(flag);
    }
    build.compile("zones_rust_hyprland_adapter");
}
