<template>
  <div class="panel">
    <!-- 报文属性区域（报文列表 tab，或动态 tab 且无信号选中时） -->
    <template v-if="(ui.centerTab === 'messages' || isDynamicMsgTab) && msg">
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.properties') }}</div>
        <div class="field">
          <label>{{ t('panel.id') }}</label>
          <input class="mono" :value="toHex(msg.id)" @blur="e => update('id', parseHex(e.target.value))">
        </div>
        <div class="field">
          <label>{{ t('panel.name') }}</label>
          <input v-lazy-value="msg.name" @blur="e => update('name', e.target.value)">
        </div>
        <div class="field-row">
          <div class="field">
            <label>{{ t('panel.dlc') }}</label>
            <input class="mono" type="number" min="1" :max="msg.is_fd ? 64 : 8" v-lazy-value="msg.dlc" @blur="e => updateDlc(parseInt(e.target.value))">
          </div>
          <div class="field">
            <label>{{ t('panel.cycle') }}</label>
            <input class="mono" type="number" min="0" v-lazy-value="msg.cycle_time" @blur="e => update('cycle_time', parseInt(e.target.value))">
          </div>
        </div>
        <div class="field">
          <label>{{ t('panel.networkType') }}</label>
          <select ref="isFdEl" v-model="localIsFd" @change="toggleIsFd($event.target.value === 'true')">
            <option value="false">{{ t('panel.canClassic') }}</option>
            <option value="true">{{ t('panel.canfd') }}</option>
          </select>
        </div>
        <div class="field">
          <label>{{ t('panel.sender') }}</label>
          <input v-lazy-value="msg.sender" @blur="e => update('sender', e.target.value)">
        </div>
        <div class="field">
          <label>{{ t('panel.comment') }}</label>
          <textarea rows="2" v-lazy-value="msg.comment" @blur="e => update('comment', e.target.value)"></textarea>
        </div>
      </div>

      <!-- 位使用率 -->
      <div class="panel-section">
        <div class="panel-section-title">{{ t('panel.bitUsage') }}</div>
        <div class="bit-usage-bar">
          <div class="bit-usage-fill" :class="bitUsageClass" :style="{ width: bitUsagePct + '%' }"></div>
        </div>
        <div class="bit-usage-text">{{ totalBits }} / {{ maxBits }} bit</div>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-else class="panel-empty" v-html="t('panel.msgEmpty')">
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useCoreStore } from '../stores/coreStore.js'
import { useMessagesStore } from '../stores/messages.js'
import { useUiStore } from '../stores/uiStore.js'
import { toHex, parseHex } from '../utils/format.js'
import { t } from '../i18n.js'
import { vLazyValue } from '../directives/lazyValue.js'
import './panel-styles.css'

const store = useCoreStore()
const messages = useMessagesStore()
const ui = useUiStore()
const msg = computed(() => store.selectedMessage)

// 动态报文标签页时为 true（centerTab 形如 'msg_{id}'）
const isDynamicMsgTab = computed(() => typeof ui.centerTab === 'string' && ui.centerTab.startsWith('msg_'))

// ── 报文位使用率 ──
const totalBits = computed(() => {
  if (!msg.value) return 0
  return Object.values(msg.value.signals).reduce((sum, s) => sum + (s.length || 0), 0)
})
const maxBits = computed(() => (msg.value?.dlc || 0) * 8)
const bitUsagePct = computed(() => maxBits.value > 0 ? (totalBits.value / maxBits.value) * 100 : 0)
const bitUsageClass = computed(() => {
  const pct = bitUsagePct.value
  if (pct > 100) return 'danger'
  if (pct >= 80) return 'warn'
  return 'ok'
})

// 本地 is_fd 状态
const localIsFd = ref(msg.value?.is_fd ? 'true' : 'false')
const isFdEl = ref(null)
watch(() => msg.value?.is_fd, (v) => {
  localIsFd.value = v ? 'true' : 'false'
}, { immediate: true })

function update(field, value) {
  messages.updateMessageField(field, value, msg.value?.id).catch(() => {})
}

function updateDlc(value) {
  update('dlc', value)
}

function toggleIsFd(newIsFd) {
  messages.updateMessageField('is_fd', newIsFd, msg.value?.id)
    .catch(e => {
      localIsFd.value = msg.value?.is_fd ? 'true' : 'false'
      if (isFdEl.value) {
        isFdEl.value.value = localIsFd.value
      }
    })
}
</script>

<style scoped>
/* ── 位使用率 ── */
.bit-usage-bar {
  height: 8px;
  background: var(--bg-raised);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 4px;
}
.bit-usage-fill {
  height: 100%;
  border-radius: 4px;
  transition: width var(--transition);
}
.bit-usage-fill.ok { background: var(--accent); }
.bit-usage-fill.warn { background: var(--warn); }
.bit-usage-fill.danger { background: var(--danger); }
.bit-usage-text { font-size: 11px; color: var(--text-muted); }
</style>
