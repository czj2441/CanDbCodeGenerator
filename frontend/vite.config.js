/**
 * ⚠️ 启动方式注意：本项目不使用 vite dev server 直接运行。
 * 正确流程：执行 build.bat / build.sh → 后端 python -m app.server.lifecycle <port>
 * 原因：前端 WS 端口计算为 location.port + 1，只有后端启动时
 *       WS 端口才与后端 WS server 匹配。
 *       直接运行 npm run dev / npx vite 会导致 WS 端口不匹配。
 *
 * 强制约束：vite dev server (serve command) 被禁止独立启动。
 *           如需临时解除约束（仅限高级开发者调试），设置环境变量：
 *           VITE_ALLOW_DEV_SERVER=1 npx vite
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

export default defineConfig(({ command, mode }) => {
  // ── 强制约束：禁止独立启动 vite dev server ──
  if (command === 'serve' && !process.env.VITE_ALLOW_DEV_SERVER) {
    console.error('')
    console.error('╔══════════════════════════════════════════════════════════╗')
    console.error('║  ✘ Vite dev server 禁止独立启动                         ║')
    console.error('║                                                          ║')
    console.error('║  请通过 build.bat / build.sh 启动项目，                  ║')
    console.error('║  由 Python 后端统一提供 HTTP + WS 服务。                 ║')
    console.error('║                                                          ║')
    console.error('║  如需临时解除约束（仅限调试）：                          ║')
    console.error('║    VITE_ALLOW_DEV_SERVER=1 npx vite                      ║')
    console.error('╚══════════════════════════════════════════════════════════╝')
    console.error('')
    throw new Error('Vite dev server is disabled. Use build.bat / build.sh to start the project.')
  }

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
