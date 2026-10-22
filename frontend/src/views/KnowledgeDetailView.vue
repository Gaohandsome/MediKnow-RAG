<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiDoc, apiKb } from '@/api'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => Number(route.params.id))
const kb = ref(null)
const documents = ref([])
const loading = ref(false)
let timer = null

const statusMeta = {
  pending: { text: '排队中', type: 'info' },
  processing: { text: '解析中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
}

const pendingCount = computed(
  () => documents.value.filter((doc) => ['pending', 'processing'].includes(doc.status)).length,
)

const fileIcons = {
  PDF: { icon: 'Document', color: '#ef4444' },
  PPT: { icon: 'Files', color: '#f97316' },
  Word: { icon: 'Document', color: '#2563eb' },
  Markdown: { icon: 'Notebook', color: '#0ea5e9' },
  文本: { icon: 'Tickets', color: '#64748b' },
  图片: { icon: 'Picture', color: '#10b981' },
}

async function loadKb() {
  kb.value = await apiKb.detail(kbId.value)
}

async function loadDocuments(silent = false) {
  if (!silent) loading.value = true
  try {
    documents.value = await apiDoc.list(kbId.value)
  } finally {
    loading.value = false
  }
  schedulePoll()
}

function schedulePoll() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (pendingCount.value > 0) {
    timer = setTimeout(async () => {
      await loadDocuments(true)
      await loadKb()
    }, 2500)
  }
}

async function refreshAll() {
  await Promise.all([loadKb(), loadDocuments()])
}

function goUpload() {
  router.push(`/knowledge/${kbId.value}/upload`)
}

function goPreview(doc) {
  router.push(`/knowledge/${kbId.value}/documents/${doc.id}`)
}

async function reindex(doc) {
  try {
    await ElMessageBox.confirm(`将重新解析「${doc.filename}」，旧的文本块与向量会被覆盖。`, '重新解析', {
      confirmButtonText: '开始解析',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await apiDoc.reindex(doc.id)
  ElMessage.success('重新解析完成')
  refreshAll()
}

async function removeDoc(doc) {
  try {
    await ElMessageBox.confirm(`删除「${doc.filename}」后其向量数据也会被清除。`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await apiDoc.remove(doc.id)
  ElMessage.success('文档已删除')
  refreshAll()
}

function formatSize(size) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function formatTime(value) {
  return value ? value.replace('T', ' ').slice(0, 16) : '-'
}

onMounted(refreshAll)

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="page">
    <div class="crumb fade-up">
      <router-link to="/knowledge" class="back-link">
        <el-icon><ArrowLeft /></el-icon>
        知识库
      </router-link>
      <span class="sep">/</span>
      <span class="current">{{ kb?.name || '加载中…' }}</span>
    </div>

    <header v-if="kb" class="kb-head fade-up" style="animation-delay: 0.04s">
      <div class="head-main">
        <div class="badge">{{ kb.name.slice(0, 1).toUpperCase() }}</div>
        <div>
          <h1>
            {{ kb.name }}
            <el-tag size="small" effect="light" :type="kb.retrieval_mode === 'hybrid' ? 'success' : 'primary'">
              {{ kb.retrieval_mode === 'hybrid' ? '混合检索' : '稠密检索' }}
            </el-tag>
          </h1>
          <p class="desc">{{ kb.description || '暂无描述' }}</p>
        </div>
      </div>
      <div class="head-actions">
        <div class="mini-stats">
          <div><strong>{{ kb.document_count }}</strong><span>文档</span></div>
          <div><strong>{{ kb.chunk_count }}</strong><span>文本块</span></div>
          <div><strong>{{ kb.chunk_size }}</strong><span>切块</span></div>
          <div><strong>{{ kb.chunk_overlap }}</strong><span>重叠</span></div>
        </div>
        <el-button type="primary" size="large" @click="goUpload">
          <el-icon><Upload /></el-icon>
          上传文档
        </el-button>
      </div>
    </header>

    <section class="panel card fade-up" style="animation-delay: 0.08s">
      <div class="panel-head">
        <h2>文档列表</h2>
        <div class="panel-tools">
          <span v-if="pendingCount" class="parsing">
            <span class="pulse"></span>
            {{ pendingCount }} 个文档解析中，列表会自动刷新
          </span>
          <el-button text @click="refreshAll">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="documents" style="width: 100%" empty-text="还没有文档，点击右上角上传">
        <el-table-column label="文档" min-width="260">
          <template #default="{ row }">
            <div class="doc-cell">
              <div
                class="file-icon"
                :style="{ background: `${fileIcons[row.file_type]?.color || '#6366f1'}14`, color: fileIcons[row.file_type]?.color || '#6366f1' }"
              >
                <el-icon :size="17">
                  <component :is="fileIcons[row.file_type]?.icon || 'Document'" />
                </el-icon>
              </div>
              <div class="doc-name">
                <span class="name" :title="row.filename">{{ row.filename }}</span>
                <span class="meta">{{ row.file_type }} · {{ formatSize(row.file_size) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tooltip :disabled="row.status !== 'failed'" :content="row.error_message" placement="top">
              <el-tag :type="statusMeta[row.status]?.type || 'info'" effect="light" size="small">
                {{ statusMeta[row.status]?.text || row.status }}
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column prop="chunk_count" label="文本块" width="90" align="center" />

        <el-table-column label="上传时间" width="160">
          <template #default="{ row }">
            <span class="time">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="250" align="right">
          <template #default="{ row }">
            <el-button text type="primary" :disabled="row.chunk_count === 0" @click="goPreview(row)">
              预览
            </el-button>
            <el-button text @click="reindex(row)">重新解析</el-button>
            <el-button text type="danger" @click="removeDoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="documents.length === 0 && !loading" class="empty card fade-up">
      <div class="empty-icon"><el-icon :size="30"><FolderAdd /></el-icon></div>
      <h3>知识库还是空的</h3>
      <p>支持 PDF、PPT、Word、Markdown、图片，上传后会自动切块并写入向量库</p>
      <el-button type="primary" @click="goUpload">去上传文档</el-button>
    </section>
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  overflow-y: auto;
  padding: 24px 32px 40px;
}

.crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 16px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-sub);
  transition: color 0.2s ease;
}

.back-link:hover {
  color: var(--brand-1);
}

.sep {
  color: #cbd0e0;
}

.current {
  color: var(--text-main);
  font-weight: 600;
}

.kb-head {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
  padding: 22px 24px;
  border-radius: var(--radius-lg);
  background: linear-gradient(120deg, #fff 0%, #f7f7ff 55%, #f1fbff 100%);
  border: 1px solid var(--border-color);
  margin-bottom: 18px;
}

.head-main {
  display: flex;
  gap: 14px;
  align-items: center;
  min-width: 0;
}

.badge {
  width: 52px;
  height: 52px;
  flex: 0 0 52px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
  box-shadow: 0 10px 22px rgba(99, 102, 241, 0.28);
}

.head-main h1 {
  font-size: 21px;
  display: flex;
  align-items: center;
  gap: 10px;
  letter-spacing: -0.3px;
}

.desc {
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 12.5px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 22px;
}

.mini-stats {
  display: flex;
  gap: 18px;
}

.mini-stats div {
  text-align: center;
}

.mini-stats strong {
  display: block;
  font-size: 17px;
  color: var(--text-main);
}

.mini-stats span {
  font-size: 11px;
  color: var(--text-muted);
}

.panel {
  padding: 18px 20px 8px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.panel-head h2 {
  font-size: 15px;
}

.panel-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}

.parsing {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #b45309;
}

.pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f59e0b;
  animation: pulseSoft 1.4s ease-in-out infinite;
}

.doc-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.file-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
}

.doc-name {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.doc-name .name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.doc-name .meta {
  font-size: 11.5px;
  color: var(--text-muted);
}

.time {
  color: var(--text-muted);
  font-size: 12.5px;
}

.empty {
  margin-top: 18px;
  padding: 46px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
}

.empty-icon {
  width: 66px;
  height: 66px;
  border-radius: 20px;
  display: grid;
  place-items: center;
  color: var(--brand-1);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(34, 211, 238, 0.1));
}

.empty p {
  color: var(--text-muted);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .mini-stats {
    display: none;
  }
}
</style>
