<template>
  <div
    class="toast-container"
    @mouseenter="ui.resetCountdown()"
    @mouseleave="ui.resumeCountdown()"
  >
    <TransitionGroup name="toast">
      <div
        v-for="(t, idx) in ui.visibleToasts"
        :key="t.id"
        class="toast"
        :class="{ error: t.isError }"
      >
        <div class="toast-body">
          <span class="toast-text">{{ t.text }}</span>
          <button class="toast-close" @click="ui.removeToast(t.id)">&times;</button>
        </div>
        <!-- 进度条：仅在队首 toast 上显示 -->
        <div
          v-if="idx === 0"
          class="toast-progress"
          :style="{ transform: `scaleX(${ui.headProgress})` }"
        />
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import { useUiStore } from '../stores/uiStore.js'

const ui = useUiStore()

function handleVisibility() {
  if (document.hidden) {
    ui.resetCountdown()
  } else {
    ui.resumeCountdown()
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<style scoped>
.toast-container {
  position: fixed;
  bottom: 40px;
  right: 24px;
  z-index: 200;
  display: flex;
  flex-direction: column-reverse;
  align-items: flex-end;
  gap: 8px;
}

.toast {
  position: relative;
  display: flex;
  flex-direction: column;
  background: var(--bg-raised);
  border: 1px solid var(--border-light);
  color: var(--text);
  border-radius: var(--radius);
  font-size: 12px;
  box-shadow: var(--shadow);
  max-width: 380px;
  overflow: hidden;
}

.toast-body {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px 10px 18px;
}

.toast.error {
  background: oklch(0.22 0.05 25);
  border-color: oklch(0.40 0.10 25);
  color: oklch(0.85 0.05 25);
}

.toast-text {
  flex: 1;
  word-break: break-word;
}

.toast-close {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  font-size: 16px;
  line-height: 1;
  opacity: 0.5;
  cursor: pointer;
  transition: opacity 150ms, background 150ms;
}
.toast-close:hover {
  opacity: 1;
  background: oklch(1 0 0 / 0.1);
}

/* ── 进度条 ── */
.toast-progress {
  height: 3px;
  background: oklch(0.75 0.05 25);
  transform-origin: left;
  will-change: transform;
}
.toast:not(.error) > .toast-progress {
  background: oklch(0.7 0.1 240);
}

/* ── TransitionGroup 动画 ── */
.toast-enter-active, .toast-leave-active {
  transition: all 200ms ease;
}
.toast-enter-from, .toast-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
.toast-move {
  transition: transform 200ms ease;
}
</style>
