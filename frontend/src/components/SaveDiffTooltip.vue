<template>
  <Transition name="diff-fade">
    <div
      v-if="visible"
      class="save-diff-tooltip"
      @mouseenter="$emit('enter')"
      @mouseleave="$emit('leave')"
    >
      <div class="diff-header">{{ t('diff.title') }}</div>
      <div class="diff-body">
        <div v-if="loading" class="diff-status">{{ t('diff.loading') }}</div>
        <div v-else-if="error" class="diff-status diff-error">{{ error }}</div>
        <div v-else-if="entries.length === 0" class="diff-status">{{ t('diff.noChanges') }}</div>
        <ul v-else class="diff-list">
          <li
            v-for="(entry, idx) in entries"
            :key="idx"
            class="diff-item"
            :class="'diff-' + entry.type"
          >
            <span class="diff-badge">{{ badgeLabel(entry.type) }}</span>
            <span class="diff-path">{{ entry.path }}</span>
            <template v-if="entry.type === 'modified'">
              <span class="diff-old">{{ entry.old }}</span>
              <span class="diff-arrow">→</span>
              <span class="diff-new">{{ entry.new }}</span>
            </template>
          </li>
        </ul>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { t } from '../i18n.js'

defineProps({
  visible: Boolean,
  loading: Boolean,
  error: { type: String, default: '' },
  entries: { type: Array, default: () => [] },
})

defineEmits(['enter', 'leave'])

function badgeLabel(type) {
  if (type === 'added') return '[+]'
  if (type === 'removed') return '[-]'
  return '[~]'
}
</script>

<style scoped>
.save-diff-tooltip {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
  z-index: 200;
  width: 420px;
  max-height: 400px;
  display: flex;
  flex-direction: column;
  pointer-events: auto;
}

.diff-header {
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  letter-spacing: 0.3px;
  text-transform: uppercase;
  flex-shrink: 0;
}

.diff-body {
  overflow-y: auto;
  flex: 1;
  padding: 4px 0;
}

.diff-status {
  padding: 10px 14px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}

.diff-error {
  color: var(--danger);
}

.diff-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.diff-item {
  display: flex;
  align-items: baseline;
  gap: 4px;
  padding: 3px 12px;
  font-size: 12px;
  font-family: var(--font-mono);
  line-height: 1.5;
}

.diff-badge {
  font-weight: 700;
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.diff-added .diff-badge { color: var(--accent); }
.diff-removed .diff-badge { color: var(--danger); }
.diff-modified .diff-badge { color: var(--warn); }

.diff-path {
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
}

.diff-old {
  color: var(--danger);
  text-decoration: line-through;
  flex-shrink: 0;
}

.diff-arrow {
  color: var(--text-muted);
  flex-shrink: 0;
  margin: 0 2px;
}

.diff-new {
  color: var(--accent);
  flex-shrink: 0;
}

.diff-fade-enter-active,
.diff-fade-leave-active {
  transition: opacity 120ms ease;
}
.diff-fade-enter-from,
.diff-fade-leave-to {
  opacity: 0;
}
</style>
