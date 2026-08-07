<template>
  <SignalLayoutVisualizer v-if="ui.layoutViewMode" :msg-id="msgId" />
  <SignalTable v-else :msg-id="msgId" />
</template>

<script setup>
import { useUiStore } from '../stores/uiStore.js'
import SignalTable from './SignalTable.vue'
import SignalLayoutVisualizer from './SignalLayoutVisualizer.vue'

defineProps({
  msgId: { type: Number, required: true },
})

const ui = useUiStore()
</script>
