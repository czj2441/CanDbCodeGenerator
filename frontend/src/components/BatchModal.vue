<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="modal-overlay" @mousedown.self="close">
        <div class="modal-panel">
          <div class="modal-header">{{ t('batch.title') }}</div>
          <div class="modal-body">
            <!-- 左侧：表单 -->
            <div class="form-side">
              <div class="field">
                <label>{{ t('batch.nameTemplate') }}</label>
                <input class="mono" v-model="form.nameTemplate" spellcheck="false">
                <div class="hint">{{ t('batch.nameHint') }}</div>
              </div>
              <div class="row">
                <div class="field">
                  <label>{{ t('batch.count') }}</label>
                  <input class="mono" type="number" v-model.number="form.count" min="1" max="64">
                </div>
                <div class="field">
                  <label>{{ t('batch.startNum') }}</label>
                  <input class="mono" type="number" v-model.number="form.startNum" min="0">
                </div>
              </div>
              <div class="row">
                <div class="field">
                  <label>{{ t('batch.startBit') }}</label>
                  <input class="mono" type="number" v-model.number="form.startBit" min="0" max="63">
                </div>
                <div class="field">
                  <label>{{ t('batch.interval') }}</label>
                  <input class="mono" type="number" v-model.number="form.interval" min="0" max="64">
                </div>
              </div>
              <div class="row">
                <div class="field">
                  <label>{{ t('batch.length') }}</label>
                  <input class="mono" type="number" v-model.number="form.length" min="1" max="64">
                </div>
                <div class="field">
                  <label>{{ t('batch.byteOrder') }}</label>
                  <select v-model="form.byteOrder">
                    <option value="intel">{{ t('batch.intel') }}</option>
                    <option value="motorola">{{ t('batch.motorola') }}</option>
                  </select>
                </div>
              </div>
              <div class="field">
                <label>{{ t('batch.unit') }}</label>
                <input v-model="form.unit">
              </div>
              <div class="field">
                <label>{{ t('batch.commentTemplate') }}</label>
                <input v-model="form.commentTemplate" spellcheck="false">
                <div class="hint">{{ t('batch.commentHint') }}</div>
              </div>
            </div>

            <!-- 右侧：预览 -->
            <div class="preview-side">
              <div class="preview-label">{{ t('batch.previewTitle') }}</div>
              <div class="preview-canvas-wrap">
                <BitLayoutCanvas
                  :signals="canvasSignals"
                  :dlc="currentMsgDlc"
                />
              </div>
              <div class="preview-table-wrap">
                <table class="preview-table">
                  <thead>
                    <tr>
                      <th>{{ t('signal.thName') }}</th>
                      <th>{{ t('signal.thStart') }}</th>
                      <th>{{ t('signal.thLen') }}</th>
                      <th>{{ t('signal.thOrder') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(sig, idx) in previewSignals" :key="idx"
                        :class="{ 'invalid': sig._invalid }">
                      <td class="mono">{{ sig.name }}</td>
                      <td class="mono">{{ sig.display_start_bit }}<span v-if="sig._invalid" class="invalid-mark">{{ t('batch.invalid') }}</span></td>
                      <td class="mono">{{ sig.length }}</td>
                      <td>{{ sig.byte_order === 'intel' ? t('batch.intel') : t('batch.motorola') }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="close">{{ t('batch.cancel') }}</button>
            <button class="btn btn-accent" @click="create">{{ t('batch.create') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { useSignalsStore } from '../stores/signals.js'
import { useEditorStore } from '../stores/editor.js'
import { t } from '../i18n.js'
import { expandTemplate } from '../utils/format.js'
import { computeBatchSignals } from '../utils/signalLayout.js'
import BitLayoutCanvas from './BitLayoutCanvas.vue'

const signals = useSignalsStore()
const editor = useEditorStore()

const visible = defineModel('visible', { type: Boolean, default: false })

const createDefaultForm = () => ({
  nameTemplate: 'PTA{n:02d}_AdVal',
  count: 8,
  startNum: 1,
  startBit: 0,
  interval: 0,
  length: 8,
  byteOrder: 'motorola',
  factor: 1.0,
  offset: 0.0,
  minVal: 0.0,
  maxVal: 0.0,
  unit: '',
  commentTemplate: '',
})

const form = reactive(createDefaultForm())

// 每次打开模态框时重置表单
watch(visible, (newVal) => {
  if (newVal) {
    Object.assign(form, createDefaultForm())
  }
})

// ── 预览计算 ──

/** 当前报文的 DLC（字节数），默认 8 */
const currentMsgDlc = computed(() => {
  const msg = editor.selectedMessage
  return msg?.dlc || 8
})

/** 预览信号列表（纯前端计算，不经过后端）
 *  用户输入的 startBit 为 LSB（与信号列表显示一致），存储格式为 MSB（Motorola）供 BitLayoutCanvas 渲染 */
const previewSignals = computed(() => {
  const result = []
  const count = Math.max(0, Math.min(form.count || 0, 64))
  const length = form.length || 1
  const byteOrder = form.byteOrder || 'motorola'
  const interval = form.interval || 0
  const layouts = computeBatchSignals({
    startBit: form.startBit || 0,
    length,
    interval,
    byteOrder,
    count,
    maxBit: currentMsgDlc.value * 8 - 1,
  })
  for (let i = 0; i < count; i++) {
    const n = (form.startNum || 0) + i
    const name = expandTemplate(form.nameTemplate || '', n)
    const layout = layouts[i]
    result.push({
      name,
      start_bit: layout.start_bit,
      display_start_bit: layout.display_start_bit,
      length,
      byte_order: byteOrder,
      _invalid: !layout.valid,
    })
  }
  return result
})

/** 画布只渲染有效信号 */
const canvasSignals = computed(() => previewSignals.value.filter(sig => !sig._invalid))

function close() {
  visible.value = false
}

async function create() {
  await signals.batchAddSignals({ ...form })
  close()
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: oklch(0.08 0.01 260 / 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 900px;
  max-width: 94vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow);
}

.modal-header {
  padding: 14px 18px;
  font-size: 14px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}

.modal-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ── 左侧表单 ── */
.form-side {
  flex: 1;
  padding: 14px 16px 14px 18px;
  overflow-y: auto;
  border-right: 1px solid var(--border);
}

/* ── 右侧预览 ── */
.preview-side {
  width: 380px;
  min-width: 300px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 14px 18px 14px 16px;
}

.preview-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.preview-canvas-wrap {
  flex: 0 0 auto;
  max-height: 280px;
  overflow: auto;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
}

.preview-table-wrap {
  flex: 1;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.preview-table th {
  position: sticky;
  top: 0;
  background: var(--bg-raised);
  border-bottom: 1px solid var(--border);
  padding: 4px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-muted);
  z-index: 1;
}
.preview-table td {
  padding: 3px 6px;
  border-bottom: 1px solid color-mix(in oklch, var(--border) 40%, transparent);
  color: var(--text);
}
.preview-table .mono {
  font-family: var(--font-mono);
}
.preview-table tr.invalid td {
  background: oklch(0.32 0.14 15 / 0.35);
  color: oklch(0.78 0.17 25);
  text-decoration: line-through;
}
.invalid-mark {
  margin-left: 6px;
  font-size: 10px;
  border: 1px solid oklch(0.65 0.18 25);
  border-radius: 3px;
  padding: 0 4px;
  text-decoration: none;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--border);
}

.field { margin-bottom: 10px; }
.field label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 3px;
}
.field input, .field select {
  width: 100%;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.field input:focus, .field select:focus { border-color: var(--accent-dim); }
.field input.mono { font-family: var(--font-mono); }
.field .hint {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
}

.row { display: flex; gap: 10px; }
.row .field { flex: 1; }

.btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.btn:hover { background: var(--bg-hover); }
.btn-accent {
  background: var(--accent);
  color: oklch(0.12 0.01 155);
  border-color: transparent;
  font-weight: 600;
}

.modal-enter-active, .modal-leave-active { transition: opacity 200ms; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
</style>
