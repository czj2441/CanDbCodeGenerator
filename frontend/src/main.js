import { migrateLegacyStorage } from './utils/storageMigration.js'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import VueKonva from 'vue-konva'
import App from './App.vue'

// 在 Pinia store 读取 localStorage/sessionStorage 之前完成旧键迁移
migrateLegacyStorage()

const app = createApp(App)
app.use(createPinia())
app.use(VueKonva)
app.mount('#app')
