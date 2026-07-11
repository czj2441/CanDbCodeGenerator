import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { readFileSync } from 'fs'

function readVersion() {
  try {
    const c = readFileSync(resolve(__dirname, '../app/_version.py'), 'utf-8')
    const m = c.match(/MANUAL_VERSION\s*=\s*"([^"]+)"/)
    const a = c.match(/AUTO_VERSION\s*=\s*"([^"]+)"/)
    return { manual: m?.[1] || 'v00.00', auto: a?.[1] || 'dev' }
  } catch { return { manual: 'v00.00', auto: 'dev' } }
}

export default defineConfig(({ mode }) => {
  // 从.env 文件或环境变量读取后端地址（VITE_API_PROXY_TARGET）
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8080'
  const version = readVersion()

  return {
    plugins: [vue()],
    define: {
      '__MANUAL_VERSION__': JSON.stringify(version.manual),
      '__AUTO_VERSION__': JSON.stringify(version.auto),
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiProxyTarget,
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
  }
})
