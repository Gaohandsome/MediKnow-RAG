import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 局域网联调：监听所有网卡，同事可用 http://<本机内网IP>:5173 访问。
    // 只想本机用时可改回 '127.0.0.1'。
    host: true,
    port: 5173,
    // 后端仍只绑 127.0.0.1：代理请求由 Vite 进程自己发起，同机可达，
    // 不必把 8001 也暴露到局域网。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})
