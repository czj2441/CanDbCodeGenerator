<template>
  <Transition name="toast">
    <div v-if="store.toast.visible" class="toast" :class="{ error: store.toast.isError }">
      {{ store.toast.text }}
    </div>
  </Transition>
</template>

<script setup>
import { useEditorStore } from '../stores/editor.js'
const store = useEditorStore()
</script>

<style scoped>
.toast {
  position: fixed;
  bottom: 40px;
  right: 24px;
  background: var(--bg-raised);
  border: 1px solid var(--border-light);
  color: var(--text);
  padding: 10px 18px;
  border-radius: var(--radius);
  font-size: 12px;
  box-shadow: var(--shadow);
  z-index: 200;
  pointer-events: none;
}
.toast.error {
  background: oklch(0.22 0.05 25);
  border-color: oklch(0.40 0.10 25);
  color: oklch(0.85 0.05 25);
}

.toast-enter-active, .toast-leave-active {
  transition: all 200ms ease;
}
.toast-enter-from, .toast-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
</style>
