<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiDoc, apiKb } from '@/api'

const route = useRoute()
const router = useRouter()
const kbId = computed(() => Number(route.params.id))

const kb = ref(null)
const uploadRef = ref()
const fileList = ref([])
const submitting = ref(false)
const progress = ref(0)
const currentName = ref('')
const finished = ref([])

const form = reactive({
  chunk_size: 500,
  chunk_overlap: 100,
  retrieval_mode: 'hybrid',
})

const modeLocked = computed(() => (kb.value?.chunk_count || 0) > 0)

const acceptTypes = '.pdf,.pptx,.doc,.docx,.md,.markdown,.txt,.png,.jpg,.jpeg,.bmp,.webp'

const supportList = [
  { label: 'PDF', desc: '含扫描件的文字识别', color: '#ef4444' },
  { label: 'PPT', desc: '.pptx 文本与表格', color: '#f97316' },
  { label: 'Word', desc: '.docx 段落与表格', color: '#2563eb' },
  { label: 'Markdown', desc: '.md / .txt 纯文本', color: '#0ea5e9' },
  { label: '图片', desc: 'png / jpg / webp', color: '#10b981' },
]

const steps = [
  { title: '文档解析', desc: '按类型提取文本，扫描件走多模态 OCR' },
  { title: '智能切块', desc: '按段落与句子切分，保留重叠上下文' },
  { title: 'bge-m3 向量化', desc: '同时生成 1024 维稠密向量与稀疏词权重' },
  { title: '写入 Milvus', desc: '按知识库维度建集合，支持稠密/混合检索' },
]

async function loadKb() {
  kb.value = await apiKb.detail(kbId.value)
  form.chunk_size = kb.value.chunk_size
  form.chunk_overlap = kb.value.chunk_overlap
  form.retrieval_mode = kb.value.retrieval_mode
}

function onChange(file, files) {
  fileList.value = files
}

function onRemove(file, files) {
  fileList.value = files
}

function onExceed() {
  ElMessage.warning('一次最多上传 10 个文件')
}

async function submit() {
  if (!fileList.value.length) {
    ElMessage.warning('请先选择要解析的文档')
    return
  }
  if (form.chunk_overlap >= form.chunk_size) {
    ElMessage.warning('重叠大小必须小于切块大小')
    return
  }

  submitting.value = true
  finished.value = []
  try {
    for (let index = 0; index < fileList.value.length; index += 1) {
      const item = fileList.value[index]
      currentName.value = item.name
      progress.value = 0
      const formData = new FormData()
      formData.append('file', item.raw)
      formData.append('chunk_size', form.chunk_size)
      formData.append('chunk_overlap', form.chunk_overlap)
      formData.append('retrieval_mode', form.retrieval_mode)

      try {
        const doc = await apiDoc.upload(kbId.value, formData, (event) => {
          if (event.total) {
            progress.value = Math.round((event.loaded / event.total) * 100)
          }
        })
        finished.value.push({ name: item.name, ok: true, id: doc.id })
      } catch (error) {
        finished.value.push({ name: item.name, ok: false, message: error?.message || '上传失败' })
      }
    }

    const okCount = finished.value.filter((item) => item.ok).length
    if (okCount > 0) {
      ElMessage.success(`${okCount} 个文档已上传，正在后台解析，可在知识库详情查看进度`)
      uploadRef.value?.clearFiles()
      fileList.value = []
      setTimeout(() => router.push(`/knowledge/${kbId.value}`), 600)
    }
  } finally {
    submitting.value = false
    progress.value = 0
    currentName.value = ''
  }
}

function goBack() {
  router.push(`/knowledge/${kbId.value}`)
}

onMounted(loadKb)
</script>

<template>
  <div class="page">
    <div class="crumb fade-up">
      <router-link to="/knowledge" class="back-link"><el-icon><ArrowLeft /></el-icon>知识库</router-link>
      <span class="sep">/</span>
      <router-link :to="`/knowledge/${kbId}`" class="back-link">{{ kb?.name || '…' }}</router-link>
      <span class="sep">/</span>
      <span class="current">文档解析</span>
    </div>

    <header class="page-head fade-up" style="animation-delay: 0.04s">
      <div>
        <h1>文档解析</h1>
        <p>上传离线文档并配置解析参数，系统会自动完成切块、向量化并写入向量库。</p>
      </div>
      <el-button @click="goBack">
        <el-icon><Back /></el-icon>
        返回知识库
      </el-button>
    </header>

    <div class="grid">
      <section class="main-col">
        <div class="card block fade-up" style="animation-delay: 0.06s">
          <div class="block-head">
            <h2>1. 选择文档</h2>
            <span class="muted">单个文件最大 50MB，支持多选</span>
          </div>

          <el-upload
            ref="uploadRef"
            drag
            multiple
            :auto-upload="false"
            :limit="10"
            :accept="acceptTypes"
            :on-change="onChange"
            :on-remove="onRemove"
            :on-exceed="onExceed"
            class="uploader"
          >
            <div class="upload-inner">
              <div class="upload-icon"><el-icon :size="26"><UploadFilled /></el-icon></div>
              <p class="upload-title">把文件拖到这里，或<em>点击选择</em></p>
              <p class="upload-sub">PDF · PPTX · DOCX · Markdown · TXT · 图片</p>
            </div>
          </el-upload>

          <div class="support-row">
            <div v-for="item in supportList" :key="item.label" class="support-item">
              <span class="dot" :style="{ background: item.color }"></span>
              <div>
                <strong>{{ item.label }}</strong>
                <span>{{ item.desc }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="card block fade-up" style="animation-delay: 0.1s">
          <div class="block-head">
            <h2>2. 配置解析参数</h2>
            <span class="muted">参数将写入知识库配置</span>
          </div>

          <div class="param-block">
            <div class="param-label">
              <span>切块大小</span>
              <strong>{{ form.chunk_size }} 字符</strong>
            </div>
            <el-slider v-model="form.chunk_size" :min="100" :max="2000" :step="50" :disabled="modeLocked" />
            <p class="param-hint">越大保留的上下文越完整，越小检索定位越精准，推荐 400~800。</p>
          </div>

          <div class="param-block">
            <div class="param-label">
              <span>重叠大小</span>
              <strong>{{ form.chunk_overlap }} 字符</strong>
            </div>
            <el-slider
              v-model="form.chunk_overlap"
              :min="0"
              :max="Math.min(500, form.chunk_size - 10)"
              :step="10"
              :disabled="modeLocked"
            />
            <p class="param-hint">相邻块之间保留的重叠内容，避免句子被切断，一般取切块大小的 10%~20%。</p>
          </div>

          <div class="param-block">
            <div class="param-label">
              <span>检索方式</span>
              <el-tag v-if="modeLocked" size="small" type="info" effect="plain">建库后不可修改</el-tag>
            </div>
            <div class="mode-row">
              <div
                class="mode-card"
                :class="{ active: form.retrieval_mode === 'hybrid', disabled: modeLocked }"
                @click="!modeLocked && (form.retrieval_mode = 'hybrid')"
              >
                <div class="mode-name">
                  <el-icon><Connection /></el-icon>
                  混合检索
                  <el-tag size="small" type="success" effect="light">推荐</el-tag>
                </div>
                <p>稠密向量 + 稀疏词权重融合，兼顾语义与关键词匹配。</p>
              </div>
              <div
                class="mode-card"
                :class="{ active: form.retrieval_mode === 'dense', disabled: modeLocked }"
                @click="!modeLocked && (form.retrieval_mode = 'dense')"
              >
                <div class="mode-name">
                  <el-icon><Aim /></el-icon>
                  稠密检索
                </div>
                <p>只使用 1024 维语义向量，写入更快，适合术语较少的资料。</p>
              </div>
            </div>
          </div>
        </div>

        <div class="submit-bar card fade-up" style="animation-delay: 0.14s">
          <div class="submit-info">
            <span class="count">{{ fileList.length }}</span>
            <div>
              <strong>个文件待解析</strong>
              <span v-if="submitting" class="running">
                正在上传 {{ currentName }} · {{ progress }}%
              </span>
              <span v-else class="muted">解析在后台进行，可随时返回查看进度</span>
            </div>
          </div>
          <el-button type="primary" size="large" :loading="submitting" @click="submit">
            <el-icon v-if="!submitting"><MagicStick /></el-icon>
            开始解析
          </el-button>
        </div>
      </section>

      <aside class="side-col">
        <div class="card block fade-up" style="animation-delay: 0.08s">
          <h2 class="side-title">解析流程</h2>
          <ol class="steps">
            <li v-for="(step, index) in steps" :key="step.title">
              <span class="step-index">{{ index + 1 }}</span>
              <div>
                <strong>{{ step.title }}</strong>
                <p>{{ step.desc }}</p>
              </div>
            </li>
          </ol>
        </div>

        <div class="card block kb-info fade-up" style="animation-delay: 0.12s">
          <h2 class="side-title">当前知识库</h2>
          <div class="info-row"><span>名称</span><strong>{{ kb?.name || '-' }}</strong></div>
          <div class="info-row">
            <span>检索方式</span>
            <strong>{{ kb?.retrieval_mode === 'hybrid' ? '混合检索' : '稠密检索' }}</strong>
          </div>
          <div class="info-row"><span>已有文档</span><strong>{{ kb?.document_count ?? 0 }}</strong></div>
          <div class="info-row"><span>已有文本块</span><strong>{{ kb?.chunk_count ?? 0 }}</strong></div>
          <p class="tip">
            提示：同一知识库内的文档应使用一致的切块与检索方式，因此建库后参数会被锁定。
          </p>
        </div>

        <div v-if="finished.length" class="card block fade-up">
          <h2 class="side-title">本次提交</h2>
          <div v-for="item in finished" :key="item.name" class="result-row">
            <el-icon :class="item.ok ? 'ok' : 'fail'">
              <component :is="item.ok ? 'CircleCheck' : 'CircleClose'" />
            </el-icon>
            <span class="result-name">{{ item.name }}</span>
          </div>
        </div>
      </aside>
    </div>
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

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 18px;
}

.page-head h1 {
  font-size: 24px;
  letter-spacing: -0.4px;
}

.page-head p {
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 13px;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 18px;
  align-items: start;
}

.main-col,
.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.main-col {
  padding-bottom: 8px;
}

.block {
  padding: 20px 22px;
}

.block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 14px;
}

.block-head h2 {
  font-size: 15px;
}

.block-head .muted {
  font-size: 12px;
}

.uploader :deep(.el-upload) {
  width: 100%;
}

.uploader :deep(.el-upload-dragger) {
  width: 100%;
  padding: 28px 20px;
  border-radius: 16px;
  border: 1.5px dashed rgba(99, 102, 241, 0.35);
  background: linear-gradient(160deg, #fafaff 0%, #f4fbff 100%);
  transition: all 0.25s ease;
}

.uploader :deep(.el-upload-dragger:hover) {
  border-color: var(--brand-1);
  background: linear-gradient(160deg, #f5f5ff 0%, #eefaff 100%);
  box-shadow: inset 0 0 0 1px rgba(99, 102, 241, 0.08);
}

.upload-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.upload-icon {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  color: #fff;
  background: var(--gradient-brand);
  box-shadow: 0 12px 24px rgba(99, 102, 241, 0.28);
  margin-bottom: 6px;
  animation: pulseSoft 3s ease-in-out infinite;
}

.upload-title {
  font-size: 14px;
  color: var(--text-main);
}

.upload-title em {
  color: var(--brand-1);
  font-style: normal;
  font-weight: 600;
}

.upload-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.support-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 20px;
  margin-top: 16px;
}

.support-item {
  display: flex;
  align-items: flex-start;
  gap: 7px;
}

.support-item .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 7px;
}

.support-item strong {
  display: block;
  font-size: 12.5px;
}

.support-item span {
  font-size: 11.5px;
  color: var(--text-muted);
}

.param-block + .param-block {
  margin-top: 22px;
}

.param-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 6px;
}

.param-label strong {
  color: var(--brand-1);
  font-size: 13px;
}

.param-hint {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-top: 2px;
}

.mode-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.mode-card {
  padding: 14px;
  border-radius: 14px;
  border: 1.5px solid var(--border-color);
  cursor: pointer;
  transition: all 0.22s ease;
}

.mode-card:hover {
  border-color: rgba(99, 102, 241, 0.4);
}

.mode-card.active {
  border-color: var(--brand-1);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.07), rgba(139, 92, 246, 0.05));
  box-shadow: 0 10px 22px rgba(99, 102, 241, 0.12);
}

.mode-card.disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.mode-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13.5px;
  margin-bottom: 4px;
}

.mode-card p {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.65;
}

.submit-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 22px;
  background: rgba(255, 255, 255, 0.92);
}

.submit-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.count {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  background: var(--gradient-brand);
}

.submit-info strong {
  display: block;
  font-size: 13.5px;
}

.submit-info span {
  font-size: 12px;
}

.running {
  color: var(--brand-1);
}

.side-title {
  font-size: 14px;
  margin-bottom: 14px;
}

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 16px;
}

.steps li {
  display: flex;
  gap: 12px;
  position: relative;
}

.steps li:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 12px;
  top: 28px;
  bottom: -14px;
  width: 1px;
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.35), rgba(99, 102, 241, 0.05));
}

.step-index {
  width: 25px;
  height: 25px;
  flex: 0 0 25px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.12);
}

.steps strong {
  font-size: 13px;
}

.steps p {
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.6;
  margin-top: 2px;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 0;
  font-size: 12.5px;
  border-bottom: 1px dashed var(--border-color);
}

.info-row span {
  color: var(--text-muted);
}

.tip {
  margin-top: 12px;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--text-sub);
  background: rgba(99, 102, 241, 0.06);
  border-radius: 10px;
  padding: 10px;
}

.result-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  padding: 5px 0;
}

.result-row .ok {
  color: #16a34a;
}

.result-row .fail {
  color: #ef4444;
}

.result-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
