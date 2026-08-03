/**
 * ⚠️ 启动方式注意：本项目不使用 vite dev server 直接运行。
 * 正确流程：执行 build.bat → 后端 python -m app.server.lifecycle 8080
 * 原因：前端 WS 端口计算为 location.port + 1，只有后端在 8080 运行时
 *       WS 端口才等于 8081，与后端 WS server 匹配。
 *       直接运行 npm run dev (port 5173) 会导致 WS 端口不匹配。
 */
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { readFileSync } from 'fs'

function readVersion() {
  let manual = 'v01.00', auto = 'dev'
  try {
    const c = readFileSync(resolve(__dirname, '../app/_version.py'), 'utf-8')
    const m = c.match(/MANUAL_VERSION\s*=\s*"([^"]+)"/)
    if (m) manual = m[1]
  } catch { /* keep default */ }
  try {
    const c = readFileSync(resolve(__dirname, '../app/_auto_version.py'), 'utf-8')
    const a = c.match(/AUTO_VERSION\s*=\s*"([^"]+)"/)
    if (a) auto = a[1]
  } catch { /* keep default */ }
  return { manual, auto }
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
  }
})
