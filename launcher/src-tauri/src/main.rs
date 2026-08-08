// Todo o app fica em lib.rs (`run()`); main.rs so existe pra dar o entry
// point nativo (convencao do template Tauri v2, compativel com build mobile
// no futuro sem duplicar codigo).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    limerence_launcher_lib::run();
}
