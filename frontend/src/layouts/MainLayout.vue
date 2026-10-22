<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import BrandLogo from '@/components/BrandLogo.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const navItems = [
  { name: 'chat', path: '/chat', label: '智能问答', icon: 'ChatDotRound', hint: '基于院内资料提问' },
  { name: 'knowledge', path: '/knowledge', label: '知识库', icon: 'Collection', hint: '指南与制度解析' },
]

const activeName = computed(() => {
  if (route.path.startsWith('/knowledge')) return 'knowledge'
  return 'chat'
})

const initial = computed(() => (authStore.displayName || '访').slice(0, 1).toUpperCase())

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  authStore.logout()
  ElMessage.success('已退出登录')
  router.replace('/login')
}

onMounted(() => {
  authStore.fetchMe()
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand-row">
        <BrandLogo :size="34" />
      </div>

      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="item.path"
          class="nav-item"
          :class="{ active: activeName === item.name }"
        >
          <span class="icon-wrap">
            <el-icon :size="18">
              <component :is="item.icon" />
            </el-icon>
          </span>
          <span class="text">
            <span class="label">{{ item.label }}</span>
            <span class="hint">{{ item.hint }}</span>
          </span>
          <span class="bar"></span>
        </router-link>
      </nav>

      <div class="side-note">
        <div class="note-title">使用小贴士</div>
        <p>先在「知识库」上传诊疗规范或院内制度完成解析，再回到问答页勾选后提问；系统仅依据检索到的原文作答。</p>
      </div>

      <el-dropdown trigger="click" placement="top-start" popper-class="user-menu">
        <div class="user">
          <div class="avatar">{{ initial }}</div>
          <div class="meta">
            <strong>{{ authStore.displayName }}</strong>
            <span>已登录</span>
          </div>
          <el-icon class="more"><MoreFilled /></el-icon>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>
              <el-icon><User /></el-icon>
              {{ authStore.user?.username || '-' }}
            </el-dropdown-item>
            <el-dropdown-item divided @click="handleLogout">
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </aside>

    <main class="content">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  width: 248px;
  flex: 0 0 248px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px 18px 18px;
  background: #fff;
  border-right: 1px solid var(--border-color);
}

.brand-row {
  padding: 2px 6px 6px;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 12px;
  border-radius: 14px;
  color: var(--text-sub);
  transition: background 0.22s ease, color 0.22s ease, transform 0.22s ease;
  overflow: hidden;
}

.nav-item:hover {
  background: #f5f6ff;
  color: var(--text-main);
  transform: translateX(2px);
}

.nav-item.active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(139, 92, 246, 0.1));
  color: #4f46e5;
}

.icon-wrap {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: #f3f4fb;
  color: #6b7280;
  transition: all 0.22s ease;
}

.nav-item.active .icon-wrap {
  background: var(--gradient-brand);
  color: #fff;
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.3);
}

.text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.label {
  font-size: 14px;
  font-weight: 600;
}

.hint {
  font-size: 11px;
  color: var(--text-muted);
}

.bar {
  position: absolute;
  left: 0;
  top: 50%;
  width: 3px;
  height: 0;
  border-radius: 0 4px 4px 0;
  background: var(--gradient-brand);
  transform: translateY(-50%);
  transition: height 0.25s ease;
}

.nav-item.active .bar {
  height: 20px;
}

.side-note {
  margin-top: auto;
  padding: 14px;
  border-radius: 16px;
  background: linear-gradient(160deg, #f7f7ff 0%, #f2fbff 100%);
  border: 1px dashed rgba(99, 102, 241, 0.28);
}

.note-title {
  font-size: 12px;
  font-weight: 700;
  color: #4f46e5;
  margin-bottom: 6px;
}

.side-note p {
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--text-sub);
}

.user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 14px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.user:hover {
  background: #f5f6ff;
}

.avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 11px;
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
}

.meta {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  flex: 1;
  overflow: hidden;
}

.meta strong {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.meta span {
  font-size: 11px;
  color: var(--text-muted);
}

.more {
  color: var(--text-muted);
}

.content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-page);
}

@media (max-width: 900px) {
  .sidebar {
    width: 76px;
    flex: 0 0 76px;
    padding: 18px 10px;
  }

  .brand-row :deep(.name),
  .nav-item .text,
  .side-note,
  .user .meta,
  .user .more {
    display: none;
  }

  .nav-item {
    justify-content: center;
    padding: 10px;
  }

  .user {
    justify-content: center;
  }
}
</style>
