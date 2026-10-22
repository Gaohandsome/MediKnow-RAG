<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiKb } from '@/api'

const router = useRouter()
const loading = ref(false)
const keyword = ref('')
const list = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()

const form = reactive({
  name: '',
  description: '',
  retrieval_mode: 'hybrid',
  chunk_size: 500,
  chunk_overlap: 100,
})

const rules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { max: 64, message: '名称不超过 64 个字符', trigger: 'blur' },
  ],
}

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  if (!key) return list.value
  return list.value.filter(
    (item) =>
      item.name.toLowerCase().includes(key) || (item.description || '').toLowerCase().includes(key),
  )
})

const totalDocs = computed(() => list.value.reduce((sum, item) => sum + item.document_count, 0))
const totalChunks = computed(() => list.value.reduce((sum, item) => sum + item.chunk_count, 0))

async function loadList() {
  loading.value = true
  try {
    list.value = await apiKb.list()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = ''
  form.description = ''
  form.retrieval_mode = 'hybrid'
  form.chunk_size = 500
  form.chunk_overlap = 100
  dialogVisible.value = true
}

async function submitCreate() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (form.chunk_overlap >= form.chunk_size) {
    ElMessage.warning('重叠大小必须小于切块大小')
    return
  }
  submitting.value = true
  try {
    const kb = await apiKb.create({ ...form, name: form.name.trim() })
    ElMessage.success('知识库创建成功')
    dialogVisible.value = false
    await loadList()
    router.push(`/knowledge/${kb.id}`)
  } finally {
    submitting.value = false
  }
}

async function removeKb(item) {
  try {
    await ElMessageBox.confirm(
      `删除后「${item.name}」下的 ${item.document_count} 个文档与全部向量都会被清除，且不可恢复。`,
      '确认删除知识库',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await apiKb.remove(item.id)
  ElMessage.success('知识库已删除')
  loadList()
}

function formatTime(value) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

function goDetail(item) {
  router.push(`/knowledge/${item.id}`)
}

onMounted(loadList)
</script>

<template>
  <div class="page">
    <header class="page-head fade-up">
      <div>
        <h1>知识库管理</h1>
        <p>一个知识库可以上传多个文档，解析后的内容将用于问答检索。</p>
      </div>
      <div class="head-actions">
        <el-input v-model="keyword" placeholder="搜索知识库" clearable class="search">
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" size="large" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新建知识库
        </el-button>
      </div>
    </header>

    <section class="overview fade-up" style="animation-delay: 0.05s">
      <div class="overview-item">
        <span class="num">{{ list.length }}</span>
        <span class="label">知识库</span>
      </div>
      <div class="overview-item">
        <span class="num">{{ totalDocs }}</span>
        <span class="label">文档总数</span>
      </div>
      <div class="overview-item">
        <span class="num">{{ totalChunks }}</span>
        <span class="label">文本块</span>
      </div>
      <div class="overview-hint">
        <el-icon><MagicStick /></el-icon>
        提示：混合检索（稠密 + 稀疏）在中文长文档上的召回更稳，建议优先选择。
      </div>
    </section>

    <div v-loading="loading" class="grid-wrap">
      <div v-if="filtered.length" class="kb-grid">
        <article
          v-for="(item, index) in filtered"
          :key="item.id"
          class="kb-card card card-hover fade-up"
          :style="{ animationDelay: `${0.06 + index * 0.04}s` }"
          @click="goDetail(item)"
        >
          <div class="kb-top">
            <div class="kb-badge">{{ item.name.slice(0, 1).toUpperCase() }}</div>
            <div class="kb-head">
              <h3>{{ item.name }}</h3>
              <span class="tag" :class="item.retrieval_mode">
                {{ item.retrieval_mode === 'hybrid' ? '混合检索' : '稠密检索' }}
              </span>
            </div>
            <el-dropdown trigger="click" @click.stop>
              <el-button text circle class="more-btn" @click.stop>
                <el-icon><MoreFilled /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click.stop="goDetail(item)">
                    <el-icon><View /></el-icon>查看文档
                  </el-dropdown-item>
                  <el-dropdown-item divided @click.stop="removeKb(item)">
                    <el-icon><Delete /></el-icon>删除知识库
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <p class="kb-desc">{{ item.description || '暂无描述，可在详情页补充文档说明。' }}</p>

          <div class="kb-stats">
            <div class="stat">
              <strong>{{ item.document_count }}</strong>
              <span>文档</span>
            </div>
            <div class="stat">
              <strong>{{ item.chunk_count }}</strong>
              <span>文本块</span>
            </div>
            <div class="stat">
              <strong>{{ item.chunk_size }}</strong>
              <span>切块大小</span>
            </div>
          </div>

          <footer class="kb-foot">
            <span class="time">更新于 {{ formatTime(item.updated_at) }}</span>
            <span class="enter">
              进入知识库
              <el-icon><ArrowRight /></el-icon>
            </span>
          </footer>
        </article>
      </div>

      <div v-else-if="!loading" class="empty card">
        <div class="empty-art">
          <div class="ring"></div>
          <el-icon :size="34"><FolderOpened /></el-icon>
        </div>
        <h3>{{ keyword ? '没有匹配的知识库' : '还没有知识库' }}</h3>
        <p>{{ keyword ? '换个关键词试试' : '创建第一个知识库，上传文档后即可开始问答' }}</p>
        <el-button v-if="!keyword" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新建知识库
        </el-button>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" title="新建知识库" width="560px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="知识库名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：临床指南库" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            maxlength="500"
            placeholder="简单说明这个知识库收录的内容"
          />
        </el-form-item>

        <el-form-item label="检索方式">
          <div class="mode-group">
            <div
              class="mode-item"
              :class="{ active: form.retrieval_mode === 'hybrid' }"
              @click="form.retrieval_mode = 'hybrid'"
            >
              <div class="mode-title">
                混合检索
                <el-tag size="small" type="success" effect="light">推荐</el-tag>
              </div>
              <p>稠密向量 + 稀疏词权重，兼顾语义与关键词，适合中文长文档。</p>
            </div>
            <div
              class="mode-item"
              :class="{ active: form.retrieval_mode === 'dense' }"
              @click="form.retrieval_mode = 'dense'"
            >
              <div class="mode-title">稠密检索</div>
              <p>仅使用语义向量，速度快，适合表达统一、术语较少的资料。</p>
            </div>
          </div>
        </el-form-item>

        <el-form-item :label="`切块大小：${form.chunk_size} 字符`">
          <el-slider v-model="form.chunk_size" :min="100" :max="2000" :step="50" />
        </el-form-item>
        <el-form-item :label="`重叠大小：${form.chunk_overlap} 字符`">
          <el-slider v-model="form.chunk_overlap" :min="0" :max="500" :step="10" />
        </el-form-item>
        <p class="dialog-hint">切块越小定位越精准，但上下文越少；500 / 100 是通用默认值。</p>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  overflow-y: auto;
  padding: 28px 32px 40px;
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 22px;
}

.page-head h1 {
  font-size: 26px;
  letter-spacing: -0.5px;
}

.page-head p {
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 13px;
}

.head-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.search {
  width: 220px;
}

.overview {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 18px 24px;
  margin-bottom: 22px;
  border-radius: var(--radius-lg);
  background: linear-gradient(120deg, #fff 0%, #f7f7ff 60%, #f2fbff 100%);
  border: 1px solid var(--border-color);
}

.overview-item {
  display: flex;
  flex-direction: column;
}

.overview-item .num {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.5px;
  background: var(--gradient-brand);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.overview-item .label {
  font-size: 12px;
  color: var(--text-muted);
}

.overview-hint {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-sub);
}

.grid-wrap {
  min-height: 200px;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}

.kb-card {
  padding: 20px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: relative;
  overflow: hidden;
}

.kb-card::after {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: var(--gradient-brand);
  opacity: 0;
  transition: opacity 0.25s ease;
}

.kb-card:hover::after {
  opacity: 1;
}

.kb-top {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.kb-badge {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  font-weight: 700;
  font-size: 16px;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.25);
}

.kb-head {
  flex: 1;
  min-width: 0;
}

.kb-head h3 {
  font-size: 16px;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tag {
  display: inline-block;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(34, 211, 238, 0.12);
  color: #0891b2;
}

.tag.dense {
  background: rgba(139, 92, 246, 0.12);
  color: #7c3aed;
}

.more-btn {
  color: var(--text-muted);
}

.kb-desc {
  font-size: 12.5px;
  color: var(--text-sub);
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 42px;
}

.kb-stats {
  display: flex;
  gap: 10px;
}

.stat {
  flex: 1;
  padding: 8px 10px;
  border-radius: 12px;
  background: var(--bg-soft);
  text-align: center;
}

.stat strong {
  display: block;
  font-size: 16px;
  color: var(--text-main);
}

.stat span {
  font-size: 11px;
  color: var(--text-muted);
}

.kb-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-muted);
  padding-top: 4px;
}

.enter {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--brand-1);
  font-weight: 600;
  opacity: 0;
  transform: translateX(-4px);
  transition: all 0.25s ease;
}

.kb-card:hover .enter {
  opacity: 1;
  transform: translateX(0);
}

.empty {
  padding: 60px 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.empty-art {
  position: relative;
  width: 84px;
  height: 84px;
  display: grid;
  place-items: center;
  border-radius: 24px;
  color: var(--brand-1);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(34, 211, 238, 0.1));
}

.ring {
  position: absolute;
  inset: -8px;
  border-radius: 30px;
  border: 1px dashed rgba(99, 102, 241, 0.35);
  animation: pulseSoft 2.6s ease-in-out infinite;
}

.empty h3 {
  font-size: 17px;
}

.empty p {
  color: var(--text-muted);
  font-size: 13px;
}

.mode-group {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}

.mode-item {
  padding: 12px 14px;
  border-radius: 14px;
  border: 1.5px solid var(--border-color);
  cursor: pointer;
  transition: all 0.2s ease;
  background: #fff;
}

.mode-item:hover {
  border-color: rgba(99, 102, 241, 0.4);
}

.mode-item.active {
  border-color: var(--brand-1);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.07), rgba(139, 92, 246, 0.05));
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.12);
}

.mode-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13.5px;
  margin-bottom: 4px;
}

.mode-item p {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}

.dialog-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: -4px;
}

@media (max-width: 1100px) {
  .overview-hint {
    display: none;
  }
}
</style>
