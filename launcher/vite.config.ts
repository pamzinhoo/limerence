import { defineConfig } from "vite";

// Config minima pro Tauri: porta fixa (o processo Rust espera o dev server
// nela), nao limpa a tela de erro do Vite (facilita debug embutido na janela
// nativa) e ignora o watch de src-tauri (o Rust tem hot-reload proprio).
export default defineConfig({
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
});
