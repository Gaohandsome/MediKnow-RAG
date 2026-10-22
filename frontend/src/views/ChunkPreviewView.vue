<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiDoc } from '@/api'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => Number(route.params.id))
const docId = computed(() => Number(route.params.docId))

const doc = ref(null)
const chunks = ref([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')
const pagination = reactive({ page: 1, pageSize: 5 })

const editVisible = ref(false)
const editing = ref(null)
const saving = ref(false)
const editContent = ref('')

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pagination.pageSize)))

async function loadDoc() {
  doc.value = await apiDoc.detail(docId.value)
}

async function loadChunks() {
  loading.value = true
  try {
    const data = await apiDoc.chunks(docId.value, {
      page: pagination.page,
      page_size: pagination.pageSize,
      keyword: keyword.value.trim() || undefined,
    })
    chunks.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onSearch() {
  pagination.page = 1
  loadChunks()
}

function openEdit(chunk) {
  editing.value = chunk
  editContent.value = chunk.content
  editVisible.value = true
}

async function saveChunk() {
  if (!editContent.value.trim()) {
    ElMessage.warning('内容不能为空')
    return
  }
  saving.value = true
  try {
    await apiDoc.updateChunk(editing.value.id, { content: editContent.value.trim() })
    ElMessage.success('已保存，向量已同步更新')
    editVisible.value = false
    await loadChunks()
    await loadDoc()
  } finally {
    saving.value = false
  }
}

async function removeChunk(chunk) {
  try {
    await ElMessageBox.confirm('删除后该文本块将从知识库检索结果中移除。', '删除文本块', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await apiDoc.removeChunk(chunk.id)
  ElMessage.success('文本块已删除')
  if (chunks.value.length === 1 && pagination.page > 1) pagination.page -= 1
  await loadChunks()
  await loadDoc()
}

function formatSize(size) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function goBack() {
  router.push(`/knowledge/${kbId.value}`)
}

watch(
  () => pagination.page,
  () => loadChunks(),
)

onMounted(async () => {
  await Promise.all([loadDoc(), loadChunks()])
})
</script>

<template>
  <div class="page">
    <div class="crumb fade-up">
      <router-link to="/knowledge" class="back-link"><el-icon><ArrowLeft /></el-icon>知识库</router-link>
      <span class="sep">/</span>
      <router-link :to="`/knowledge/${kbId}`" class="back-link">文档列表</router-link>
      <span class="sep">/</span>
      <span class="current">知识预览</span>
    </div>

    <header v-if="doc" class="doc-head card fade-up" style="animation-delay: 0.04s">
      <div class="doc-main">
        <div class="file-badge">{{ doc.file_type }}</div>
        <div>
          <h1 :title="doc.filename">{{ doc.filename }}</h1>
          <div class="meta-row">
            <span>{{ formatSize(doc.file_size) }}</span>
            <span class="divider-dot"></span>
            <span>{{ doc.chunk_count }} 个文本块</span>
            <span class="divider-dot"></span>
            <span>{{ doc.char_count }} 字符</span>
            <span class="divider-dot"></span>
            <el-tag size="small" :type="doc.status === 'completed' ? 'success' : 'warning'" effect="light">
              {{ doc.status === 'completed' ? '解析完成' : doc.status }}
            </el-tag>
          </div>
        </div>
      </div>
      <div class="head-actions">
        <el-input
          v-model="keyword"
          placeholder="搜索文本块内容"
          clearable
          class="search"
          @keyup.enter="onSearch"
          @clear="onSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button @click="goBack">返回列表</el-button>
      </div>
    </header>

    <div class="chunk-meta fade-up" style="animation-delay: 0.08s">
      <span>共 <strong>{{ total }}</strong> 个文本块，支持直接编辑内容（会同步重建向量）</span>
      <el-pagination
        v-if="total > pagination.pageSize"
        v-model:current-page="pagination.page"
        :page-size="pagination.pageSize"
        :total="total"
        layout="prev, pager, next"
        background
      />
    </div>

    <div v-loading="loading" class="chunk-list">
      <article
        v-for="(chunk, index) in chunks"
        :key="chunk.id"
        class="chunk-card card fade-up"
        :style="{ animationDelay: `${0.02 * index}s` }"
      >
        <header class="chunk-head">
          <div class="chunk-tags">
            <span class="index">#{{ chunk.chunk_index + 1 }}</span>
            <span v-if="chunk.page > 0" class="chip">第 {{ chunk.page }} 页</span>
            <span class="muted char">{{ chunk.char_count }} 字符</span>
          </div>
          <div class="chunk-actions">
            <el-button text type="primary" size="small" @click="openEdit(chunk)">
              <el-icon><EditPen /></el-icon>
              编辑
            </el-button>
            <el-button text type="danger" size="small" @click="removeChunk(chunk)">
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </div>
        </header>
        <p class="chunk-content">{{ chunk.content }}</p>
      </article>

      <div v-if="!loading && !chunks.length" class="empty card">
        <el-icon :size="30"><DocumentDelete /></el-icon>
        <p>{{ keyword ? '没有匹配的文本块' : '该文档还没有文本块，可能仍在解析中' }}</p>
      </div>
    </div>

    <div v-if="total > pagination.pageSize" class="pager fade-up">
      <el-pagination
        v-model:current-page="pagination.page"
        :page-size="pagination.pageSize"
        :total="total"
        layout="total, prev, pager, next"
        background
      />
    </div>

    <el-dialog v-model="editVisible" title="编辑文本块" width="680px" :close-on-click-modal="false">
      <div class="edit-hint">
        修改后系统会重新计算向量并更新 Milvus，检索结果立即生效。建议保持内容完整、语义连贯。
      </div>
      <el-input v-model="editContent" type="textarea" :rows="12" maxlength="20000" show-word-limit />
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveChunk">保存并重建向量</el-button>
      </template>
    </el-dialog>
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

.doc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 22px;
  margin-bottom: 14px;
}

.doc-main {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.file-badge {
  padding: 10px 12px;
  border-radius: 14px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.24);
}

.doc-main h1 {
  font-size: 18px;
  letter-spacing: -0.3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 560px;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 5px;
  font-size: 12px;
  color: var(--text-muted);
}

.divider-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #cfd4e4;
}

.head-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.search {
  width: 220px;
}

.chunk-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.chunk-meta strong {
  color: var(--brand-1);
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 120px;
}

.chunk-card {
  padding: 16px 18px;
}

.chunk-card:hover {
  border-color: rgba(99, 102, 241, 0.25);
  box-shadow: var(--shadow-md);
}

.chunk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.chunk-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.index {
  font-size: 12px;
  font-weight: 700;
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 9px;
  border-radius: 8px;
}

.char {
  font-size: 11.5px;
}

.chunk-content {
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--text-main);
  white-space: pre-wrap;
  word-break: break-word;
}

.empty {
  padding: 46px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--text-muted);
}

.pager {
  display: flex;
  justify-content: center;
  margin-top: 18px;
}

.edit-hint {
  font-size: 12.5px;
  color: var(--text-sub);
  background: rgba(99, 102, 241, 0.06);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
  line-height: 1.7;
}
</style>
