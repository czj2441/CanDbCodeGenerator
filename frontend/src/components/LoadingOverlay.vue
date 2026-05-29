<template>
  <Transition name="fade">
    <div v-if="store.isLoading" class="loading-overlay">
      <div class="spinner"></div>
    </div>
  </Transition>
</template>

<script setup>
import { useEditorStore } from '../stores/editor.js'
const store = useEditorStore()
</script>

<style scoped>
.loading-overlay {
  position: fixed;
  inset: 0;
  background: oklch(0.10 0.005 260 / 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 150;
}
.spinner {
  width: 32px; height: 32px;
  border: 2px solid var(--border-light);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.fade-enter-active, .fade-leave-active { transition: opacity 150ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
