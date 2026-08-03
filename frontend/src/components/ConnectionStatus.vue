<template>
  <span class="api-status" :class="status">
    <span class="dot"></span>
    <template v-if="status === 'connected'">{{ t('topbar.connected') }}</template>
    <template v-else-if="status === 'dead'">{{ t('topbar.dead') }}</template>
    <template v-else>{{ t('topbar.offline') }}</template>
  </span>
</template>

<script setup>
import { t } from '../i18n.js'

defineProps({
  status: { type: String, required: true }
})
</script>

<style scoped>
.api-status {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.api-status.connected { color: var(--accent); }
.api-status.offline,
.api-status.dead { color: var(--danger); }

.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: currentColor;
  display: inline-block;
}
</style>
