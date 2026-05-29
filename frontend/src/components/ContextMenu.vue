<template>
  <Teleport to="body">
    <div
      v-if="store.contextMenu.visible"
      class="ctx-menu"
      :style="{ left: store.contextMenu.x + 'px', top: store.contextMenu.y + 'px' }"
    >
      <div
        v-for="(item, i) in items"
        :key="i"
        class="ctx-item"
        :class="{ danger: item.danger, disabled: item.disabled }"
        @click="onClick(item)"
      >
        {{ item.label }}
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { useEditorStore } from '../stores/editor.js'

const store = useEditorStore()

const props = defineProps({
  items: { type: Array, default: () => [] },
})

function onClick(item) {
  if (item.disabled) return
  store.contextMenu.visible = false
  item.action()
}
</script>

<style scoped>
.ctx-menu {
  position: fixed;
  z-index: 2000;
  min-width: 160px;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 4px 0;
  user-select: none;
}

.ctx-item {
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text);
  transition: background 100ms;
}
.ctx-item:hover:not(.disabled) {
  background: var(--bg-hover);
}
.ctx-item.danger {
  color: var(--danger);
}
.ctx-item.disabled {
  opacity: 0.35;
  cursor: default;
}
</style>
