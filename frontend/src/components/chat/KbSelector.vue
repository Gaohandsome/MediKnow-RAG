<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  kbs: { type: Array, default: () => [] },
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])
const visible = ref(false)

const selected = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const selectedNames = computed(() =>
  props.kbs.filter((item) => props.modelValue.includes(item.id)).map((item) => item.name),
)

const label = computed(() => {
  if (!selectedNames.value.length) return '未选择知识库'
  if (selectedNames.value.length === 1) return selectedNames.value[0]
  return `已选 ${selectedNames.value.length} 个知识库`
})

function toggle(id) {
  const next = selected.value.includes(id)
    ? selected.value.filter((item) => item !== id)
    : [...selected.value, id]
  selected.value = next
}

function selectAll() {
  selected.value = props.kbs.map((item) => item.id)
}

function clearAll() {
  selected.value = []
}

function onVisibleChange(value) {
  visible.value = value
}
</script>

<template>
  <el-popover
    v-model:visible="visible"
    trigger="click"
    placement="bottom-start"
    :width="340"
    popper-class="kb-popover"
    :disabled="disabled"
  >
    <template #reference>
      <button class="kb-trigger" :class="{ active: modelValue.length, disabled }" type="button">
        <span class="icon"><el-icon><Collection /></el-icon></span>
        <span class="text">
          <small>检索范围</small>
          <strong>{{ label }}</strong>
        </span>
        <el-icon class="arrow"><ArrowDown /></el-icon>
      </button>
    </template>

    <div class="pop">
      <header class="pop-head">
        <span>选择知识库（可多选）</span>
        <div class="pop-actions">
          <el-button text size="small" @click="selectAll">全选</el-button>
          <el-button text size="small" @click="clearAll">清空</el-button>
        </div>
      </header>

      <div class="kb-list">
        <div
          v-for="item in kbs"
          :key="item.id"
          class="kb-row"
          :class="{ checked: modelValue.includes(item.id) }"
          @click="toggle(item.id)"
        >
          <el-checkbox :model-value="modelValue.includes(item.id)" @click.stop @change="toggle(item.id)" />
          <div class="kb-info">
            <span class="kb-name">{{ item.name }}</span>
            <span class="kb-meta">{{ item.document_count }} 文档 · {{ item.chunk_count }} 块</span>
          </div>
        </div>

        <div v-if="!kbs.length" class="kb-empty">
          还没有知识库，先去
          <router-link to="/knowledge">知识库管理</router-link>
          创建一个吧
        </div>
      </div>

      <footer class="pop-foot">
        <span class="muted">未选择时仅用模型自身知识回答</span>
        <el-button size="small" type="primary" @click="visible = false">完成</el-button>
      </footer>
    </div>
  </el-popover>
</template>

<style scoped>
.kb-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px 7px 8px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
  background: #fff;
  cursor: pointer;
  transition: all 0.2s ease;
  max-width: 260px;
}

.kb-trigger:hover {
  border-color: rgba(99, 102, 241, 0.45);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.1);
}

.kb-trigger.active {
  border-color: rgba(99, 102, 241, 0.4);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.07), rgba(34, 211, 238, 0.05));
}

.kb-trigger.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.icon {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
}

.text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.25;
  min-width: 0;
}

.text small {
  font-size: 10.5px;
  color: var(--text-muted);
}

.text strong {
  font-size: 12.5px;
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.arrow {
  color: var(--text-muted);
  font-size: 12px;
}

.pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 600;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.pop-actions {
  display: flex;
  gap: 2px;
}

.kb-list {
  max-height: 280px;
  overflow-y: auto;
  padding: 6px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.kb-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.18s ease;
}

.kb-row:hover {
  background: #f5f6ff;
}

.kb-row.checked {
  background: rgba(99, 102, 241, 0.07);
}

.kb-info {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.kb-name {
  font-size: 13px;
}

.kb-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.kb-empty {
  padding: 22px 10px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-muted);
}

.kb-empty a {
  color: var(--brand-1);
  font-weight: 600;
}

.pop-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.pop-foot .muted {
  font-size: 11px;
}
</style>
