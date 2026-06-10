import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      // 禁用 Tree Shaking，强制打包所有模块
      treeshake: false,
      // 显式指定入口文件，确保 api-queue 被包含
      output: {
        manualChunks: {
          'vendor': ['vue', 'pinia'],
        },
      },
    },
    // 标记为保留的模块（Vite 6.x 方式）
    commonjsOptions: {
      transformMixedEsModules: true,
    },
  },
  // 确保 api-queue.js 模块被正确识别
  optimizeDeps: {
    include: ['./src/utils/api-queue.js'],
  },
})
