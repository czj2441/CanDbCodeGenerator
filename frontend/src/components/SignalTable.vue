<template>
  <div class="signal-area">
    <div class="center-header">
      <div class="center-title">
        <template v-if="msg">
          <strong>{{ msg.name || t('msglist.unnamed') }}</strong>
          — {{ toHex(msg.id) }} · {{ msg.signals.length }} {{ msg.signals.length === 1 ? t('status.signal') : t('status.signals') }}
        </template>
        <template v-else>{{ t('signal.selectMessage') }}</template>
      </div>
      <div v-if="msg" class="toolbar">
        <button class="btn" @click="addSignal">{{ t('signal.add') }}</button>
        <button class="btn btn-accent" @click="store.batchModalOpen = true">{{ t('signal.batch') }}</button>
        <button class="btn btn-danger" @click="deleteMsg">{{ t('signal.deleteMsg') }}</button>
      </div>
    </div>

    <div class="table-wrap">
      <div v-if="!msg" class="empty" v-html="t('signal.selectMessage')">
      </div>
      <div v-else-if="msg.signals.length === 0" class="empty" v-html="t('signal.empty')">
      </div>
      <table v-else class="signal-table">
        <thead>
          <tr>
            <th>{{ t('signal.thIdx') }}</th>
            <th>{{ t('signal.thName') }}</th>
            <th>{{ t('signal.thStart') }}</th>
            <th>{{ t('signal.thLen') }}</th>
            <th>{{ t('signal.thOrder') }}</th>
            <th>{{ t('signal.thFactor') }}</th>
            <th>{{ t('signal.thOffset') }}</th>
            <th>{{ t('signal.thMin') }}</th>
            <th>{{ t('signal.thMax') }}</th>
            <th>{{ t('signal.thUnit') }}</th>
            <th>{{ t('signal.thComment') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(sig, idx) in msg.signals" :key="idx" :data-sig-idx="idx">
            <td><input class="hex" :value="idx" readonly></td>
            <td><input v-model="sig.name" @blur="update(idx, 'name', sig.name)"></td>
            <td><input class="mono" type="number" v-model.number="sig.start_bit" @blur="update(idx, 'start_bit', sig.start_bit)"></td>
            <td><input class="mono" type="number" v-model.number="sig.length" @blur="update(idx, 'length', sig.length)"></td>
            <td><input class="mono" v-model="sig.byte_order" @blur="update(idx, 'byte_order', sig.byte_order)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.factor" @blur="update(idx, 'factor', sig.factor)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.offset" @blur="update(idx, 'offset', sig.offset)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.min_val" @blur="update(idx, 'min_val', sig.min_val)"></td>
            <td><input class="mono" type="number" step="any" v-model.number="sig.max_val" @blur="update(idx, 'max_val', sig.max_val)"></td>
            <td><input v-model="sig.unit" @blur="update(idx, 'unit', sig.unit)"></td>
            <td><input v-model="sig.comment" @blur="update(idx, 'comment', sig.comment)"></td>
            <td><button class="action-delete" @click="store.deleteSignal(idx)" title="删除">×</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useEditorStore } from '../stores/editor.js'
import { toHex } from '../utils/format.js'
import { t } from '../i18n.js'

const store = useEditorStore()

const msg = computed(() => store.selectedMessage)

function addSignal() {
  store.addSignal({ name: 'NewSignal', start_bit: 0, length: 8 })
}

function update(idx, field, value) {
  store.updateSignal(idx, field, value)
}

function deleteMsg() {
  if (store.selectedMsgId == null) return
  store.deleteMessage(store.selectedMsgId)
}
</script>

<style scoped>
.signal-area { display: flex; flex-direction: column; flex: 1; min-height: 0; }

.center-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.center-title {
  font-size: 13px;
  color: var(--text-dim);
}
.center-title strong { color: var(--text); font-weight: 600; }

.toolbar { display: flex; gap: 6px; }

.btn {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
}
.btn:hover { background: var(--bg-hover); }
.btn-accent { background: var(--accent); color: oklch(0.12 0.01 155); border-color: transparent; font-weight: 600; }
.btn-danger { background: oklch(0.22 0.05 25); color: oklch(0.85 0.05 25); border-color: oklch(0.35 0.08 25); }

.table-wrap { flex: 1; overflow: auto; padding: 8px; }

.empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.signal-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.signal-table th {
  text-align: left;
  padding: 6px 8px;
  color: var(--text-muted);
  font-weight: 500;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.signal-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
}
.signal-table tr:nth-child(even) { background: var(--signal-bg-alt); }
.signal-table tr:hover { background: var(--signal-bg); }

.signal-table input {
  width: 100%;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text);
  padding: 3px 5px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  outline: none;
}
.signal-table input:focus {
  background: var(--bg-raised);
  border-color: var(--accent-dim);
}
.signal-table input.mono { font-family: var(--font-mono); }
.signal-table input.hex { opacity: 0.5; text-align: center; }

.action-delete {
  background: transparent;
  border: none;
  color: var(--danger);
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
}
.action-delete:hover { color: oklch(0.75 0.15 25); }
</style>
