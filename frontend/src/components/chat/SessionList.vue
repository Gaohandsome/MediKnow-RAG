<script setup>
import { computed } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: [Number, null], default: null },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'create', 'rename', 'remove'])

const grouped = computed(() => props.sessions)

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }
  return `${date.getMonth() + 1}/${date.getDate()}`
}
</script>

<template>
  <aside class="session-panel">
    <div class="panel-top">
      <div class="title-row">
        <h2>对话</h2>
        <el-button class="new-btn" size="small" type="primary" @click="emit('create')">
          <el-icon><Plus /></el-icon>
          新建
        </el-button>
      </div>
      <p class="sub">每个会话独立保存上下文</p>
    </div>

    <div v-loading="loading" class="session-list">
      <div
        v-for="item in grouped"
        :key="item.id"
        class="session-item"
        :class="{ active: item.id === activeId }"
        @click="emit('select', item)"
      >
        <div class="session-main">
          <span class="name">{{ item.name }}</span>
          <span class="meta">
            {{ formatDate(item.last_message_at || item.created_at) }}
            <template v-if="item.kb_ids?.length"> · {{ item.kb_ids.length }} 个知识库</template>
          </span>
        </div>
        <el-dropdown trigger="click" @click.stop>
          <span class="more" @click.stop>
            <el-icon><MoreFilled /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click.stop="emit('rename', item)">
                <el-icon><EditPen /></el-icon>重命名
              </el-dropdown-item>
              <el-dropdown-item divided @click.stop="emit('remove', item)">
                <el-icon><Delete /></el-icon>删除会话
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <div v-if="!loading && !grouped.length" class="empty">
        <el-icon :size="22"><ChatLineSquare /></el-icon>
        <span>还没有对话，点击「新建」开始</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.session-panel {
  width: 258px;
  flex: 0 0 258px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color);
  background: #fcfcff;
  min-height: 0;
}

.panel-top {
  padding: 20px 16px 12px;
}

.title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.title-row h2 {
  font-size: 15px;
  letter-spacing: -0.2px;
}

.new-btn {
  border-radius: 9px;
}

.sub {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 10px 10px 12px;
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
  position: relative;
}

.session-item:hover {
  background: #f2f3fd;
}

.session-item.active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(139, 92, 246, 0.08));
}

.session-item.active::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  border-radius: 3px;
  background: var(--gradient-brand);
}

.session-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.name {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.meta {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.more {
  opacity: 0;
  color: var(--text-muted);
  padding: 2px;
  border-radius: 6px;
  transition: opacity 0.2s ease, background 0.2s ease;
}

.session-item:hover .more {
  opacity: 1;
}

.more:hover {
  background: rgba(0, 0, 0, 0.05);
}

.empty {
  margin: 20px 8px;
  padding: 22px 12px;
  border-radius: 14px;
  border: 1px dashed var(--border-strong);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 960px) {
  .session-panel {
    display: none;
  }
}
</style>
