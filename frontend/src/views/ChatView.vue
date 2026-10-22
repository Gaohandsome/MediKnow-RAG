<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiChat, apiKb } from '@/api'
import { streamChat } from '@/api/stream'
import { useAuthStore } from '@/stores/auth'
import { useSafetyStore } from '@/stores/safety'
import SessionList from '@/components/chat/SessionList.vue'
import KbSelector from '@/components/chat/KbSelector.vue'
import ParamDrawer from '@/components/chat/ParamDrawer.vue'
import MessageItem from '@/components/chat/MessageItem.vue'

const authStore = useAuthStore()
const safetyStore = useSafetyStore()

const sessions = ref([])
const kbs = ref([])
const activeId = ref(null)
const messages = ref([])
const draft = ref('')
const streaming = ref(false)
const loadingSessions = ref(false)
const loadingMessages = ref(false)
const showParams = ref(false)
const scrollRef = ref(null)
const abortCtrl = ref(null)

const models = ref([])
const limits = ref({})

const params = reactive({
  model: 'qwen-max',
  temperature: 0.7,
  top_p: 0.8,
  max_tokens: 2048,
  history_rounds: 5,
  top_k: 5,
  use_rerank: true,
})
const defaultParams = ref({ ...params })

const selectedKbIds = ref([])

const suggestions = [
  { title: '诊疗规范', text: '社区获得性肺炎的门诊经验性抗菌治疗首选什么药物？' },
  { title: '分级制度', text: '特殊使用级抗菌药物的处方权限和会诊流程是怎样的？' },
  { title: '院感防控', text: '发生锐器伤后的职业暴露处置流程分哪几步？' },
]

const activeSession = computed(() => sessions.value.find((item) => item.id === activeId.value) || null)
const headers = computed(() => ({
  kbLabel: selectedKbIds.value.length
    ? `已选 ${selectedKbIds.value.length} 个知识库`
    : '未选知识库',
}))

const inputPlaceholder = computed(() =>
  selectedKbIds.value.length
    ? '输入你的问题，回车发送，Shift + 回车换行'
    : '请先选择知识库，未选择时系统将不予作答',
)

let patchTimer = null

function scrollToBottom(smooth = true) {
  nextTick(() => {
    const el = scrollRef.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  })
}

async function loadModels() {
  const data = await apiChat.models()
  models.value = data.models || []
  limits.value = data.limits || {}
  Object.assign(params, data.defaults || {})
  defaultParams.value = { ...params }
  params.top_k = data.defaults?.top_k ?? 5
  params.use_rerank = data.defaults?.use_rerank ?? true
}

async function loadKbs() {
  kbs.value = await apiKb.options()
  // 首次进入且尚未选库时默认全选：知识库已按院内共享开放，
  // 不该让同事先撞一次「没有选知识库」的拒答才发现要手动勾。
  if (!selectedKbIds.value.length && kbs.value.length) {
    selectedKbIds.value = kbs.value.map((item) => item.id)
  }
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    sessions.value = await apiChat.sessions()
  } finally {
    loadingSessions.value = false
  }
}

function syncFromSession(session) {
  if (!session) return
  // 老会话可能建在「知识库按用户隔离」的时候，kb_ids 是空的；
  // 此时回落到当前可见的全部知识库，避免打开旧会话就问不出东西。
  const saved = session.kb_ids || []
  selectedKbIds.value = saved.length ? [...saved] : kbs.value.map((item) => item.id)
  params.model = session.model || params.model
  params.temperature = session.temperature ?? params.temperature
  params.top_p = session.top_p ?? params.top_p
  params.max_tokens = session.max_tokens ?? params.max_tokens
  params.history_rounds = session.history_rounds ?? params.history_rounds
}

async function selectSession(session) {
  if (streaming.value) {
    ElMessage.warning('正在生成回答，请稍候再切换会话')
    return
  }
  activeId.value = session.id
  syncFromSession(session)
  loadingMessages.value = true
  try {
    const data = await apiChat.messages(session.id)
    messages.value = data.map((item) => ({
      id: item.id,
      role: item.role,
      content: item.content,
      contexts: item.contexts || [],
      plan: item.plan || {},
      latency_ms: item.latency_ms,
    }))
    scrollToBottom(false)
  } finally {
    loadingMessages.value = false
  }
}

async function createSession(silent = false) {
  const data = await apiChat.createSession({
    name: '新对话',
    kb_ids: selectedKbIds.value,
    model: params.model,
    temperature: params.temperature,
    top_p: params.top_p,
    max_tokens: params.max_tokens,
    history_rounds: params.history_rounds,
  })
  sessions.value = [data, ...sessions.value]
  activeId.value = data.id
  messages.value = []
  if (!silent) ElMessage.success('已新建对话')
  return data
}

async function renameSession(session) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话名称', '重命名会话', {
      inputValue: session.name,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (val) => (val && val.trim() ? true : '名称不能为空'),
    })
    const updated = await apiChat.updateSession(session.id, { name: value.trim() })
    Object.assign(session, updated)
    ElMessage.success('已重命名')
  } catch {
    /* 取消 */
  }
}

async function removeSession(session) {
  try {
    await ElMessageBox.confirm(`删除会话「${session.name}」后，其中的聊天记录将不可恢复。`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await apiChat.removeSession(session.id)
  sessions.value = sessions.value.filter((item) => item.id !== session.id)
  if (activeId.value === session.id) {
    activeId.value = null
    messages.value = []
  }
  ElMessage.success('会话已删除')
}

function schedulePatch() {
  if (!activeId.value) return
  if (patchTimer) clearTimeout(patchTimer)
  patchTimer = setTimeout(async () => {
    try {
      await apiChat.updateSession(activeId.value, {
        kb_ids: selectedKbIds.value,
        model: params.model,
        temperature: params.temperature,
        top_p: params.top_p,
        max_tokens: params.max_tokens,
        history_rounds: params.history_rounds,
      })
    } catch {
      /* 忽略参数同步失败 */
    }
  }, 450)
}

function onKbChange(value) {
  selectedKbIds.value = value
  schedulePatch()
}

function onParamsChange(value) {
  Object.assign(params, value)
  schedulePatch()
}

function resetParams() {
  Object.assign(params, defaultParams.value)
  params.top_k = defaultParams.value.top_k ?? 5
  params.use_rerank = defaultParams.value.use_rerank ?? true
  schedulePatch()
}

function useSuggestion(text) {
  draft.value = text
  send()
}

async function send() {
  const question = draft.value.trim()
  if (!question || streaming.value) return

  let sessionId = activeId.value
  if (!sessionId) {
    const session = await createSession(true)
    sessionId = session.id
  }

  draft.value = ''
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: question })
  const assistant = reactive({
    id: `a-${Date.now()}`,
    role: 'assistant',
    content: '',
    contexts: [],
    plan: {},
    latency_ms: 0,
    safety: null,
  })
  messages.value.push(assistant)
  streaming.value = true
  scrollToBottom()

  abortCtrl.value = new AbortController()

  await streamChat(
    {
      session_id: sessionId,
      question,
      kb_ids: selectedKbIds.value,
      model: params.model,
      temperature: params.temperature,
      top_p: params.top_p,
      max_tokens: params.max_tokens,
      history_rounds: params.history_rounds,
      top_k: params.top_k,
      use_rerank: params.use_rerank,
    },
    {
      signal: abortCtrl.value.signal,
      onMeta: (event) => {
        if (event.session_name) {
          const target = sessions.value.find((item) => item.id === event.session_id)
          if (target) target.name = event.session_name
        }
      },
      onPlan: (event) => {
        assistant.plan = {
          ...assistant.plan,
          intent: event.intent,
          strategy: event.strategy,
          need_retrieval: event.need_retrieval,
          variants: event.variants || [],
        }
      },
      onCache: (event) => {
        assistant.plan = {
          ...assistant.plan,
          cache_hit: event.hit,
          cache_source: event.source,
          cache_score: event.score,
        }
      },
      onContexts: (list) => {
        assistant.contexts = list
        scrollToBottom()
      },
      onSafety: (event) => {
        assistant.safety = event
        if (event.notice) scrollToBottom()
      },
      onDelta: (text) => {
        assistant.content += text
        scrollToBottom()
      },
      onWarning: (message) => {
        ElMessage.warning(message)
      },
      onDone: (event) => {
        assistant.latency_ms = event.latency_ms || 0
        if (event.contexts) assistant.contexts = event.contexts
        if (event.plan) assistant.plan = { ...assistant.plan, ...event.plan }
        if (event.message_id) assistant.id = event.message_id
        loadSessions()
      },
      onError: (message) => {
        assistant.content = assistant.content || `回答生成失败：${message}`
        ElMessage.error(message)
      },
    },
  )

  streaming.value = false
  abortCtrl.value = null
  await loadSessions()
}

function stop() {
  abortCtrl.value?.abort()
  streaming.value = false
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

watch(
  () => messages.value.length,
  () => scrollToBottom(),
)

onMounted(async () => {
  await Promise.all([loadModels(), loadKbs(), loadSessions(), safetyStore.load()])
  if (sessions.value.length) {
    await selectSession(sessions.value[0])
  }
})

onBeforeUnmount(() => {
  if (patchTimer) clearTimeout(patchTimer)
  abortCtrl.value?.abort()
})
</script>

<template>
  <div class="chat-page">
    <SessionList
      :sessions="sessions"
      :active-id="activeId"
      :loading="loadingSessions"
      @select="selectSession"
      @create="createSession(false)"
      @rename="renameSession"
      @remove="removeSession"
    />

    <div class="chat-main">
      <header class="chat-head">
        <div class="head-left">
          <h1>{{ activeSession?.name || '智能问答' }}</h1>
          <span class="model-chip">
            <el-icon><Cpu /></el-icon>
            {{ params.model }}
          </span>
          <span v-if="params.use_rerank" class="model-chip soft">重排开启</span>
        </div>

        <div class="head-right">
          <KbSelector :kbs="kbs" :model-value="selectedKbIds" :disabled="streaming" @update:model-value="onKbChange" />
          <el-button circle class="param-btn" title="推理参数" @click="showParams = true">
            <el-icon><Setting /></el-icon>
          </el-button>
        </div>
      </header>

      <div ref="scrollRef" v-loading="loadingMessages" class="messages">
        <div v-if="!messages.length" class="welcome fade-up">
          <div class="welcome-glow"></div>
          <div class="welcome-icon"><el-icon :size="26"><ChatDotRound /></el-icon></div>
          <h2>你好，{{ authStore.displayName }}</h2>
          <p>选择一个院内知识库，如诊疗规范、药品说明书或管理制度，答案会带上原文出处。</p>

          <div class="suggestions">
            <button
              v-for="item in suggestions"
              :key="item.title"
              class="suggestion"
              type="button"
              @click="useSuggestion(item.text)"
            >
              <span class="s-title">{{ item.title }}</span>
              <span class="s-text">{{ item.text }}</span>
              <el-icon class="s-arrow"><Right /></el-icon>
            </button>
          </div>
        </div>

        <div v-else class="message-list">
          <MessageItem
            v-for="(item, index) in messages"
            :key="item.id || index"
            :message="{ ...item, userInitial: authStore.displayName.slice(0, 1) }"
            :streaming="streaming && index === messages.length - 1 && item.role === 'assistant'"
            :show-disclaimer="index === messages.length - 1 && item.role === 'assistant'"
          />
        </div>
      </div>

      <footer class="composer">
        <div class="composer-inner">
          <el-input
            v-model="draft"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            resize="none"
            :placeholder="inputPlaceholder"
            :disabled="streaming"
            class="composer-input"
            @keydown="onKeydown"
          />
          <div class="composer-actions">
            <span class="hint-line">
              <template v-if="selectedKbIds.length">
                检索范围：{{ headers.kbLabel }}
              </template>
              <template v-else>建议先在右侧选择知识库</template>
            </span>
            <el-button v-if="streaming" class="stop-btn" @click="stop">
              <el-icon><VideoPause /></el-icon>
              停止
            </el-button>
            <el-button v-else class="send-btn btn-gradient" :disabled="!draft.trim()" @click="send">
              发送
              <el-icon><Promotion /></el-icon>
            </el-button>
          </div>
        </div>
        <p class="disclaimer">{{ safetyStore.disclaimer }}</p>
      </footer>
    </div>

    <ParamDrawer
      v-model="showParams"
      :models="models"
      :params="params"
      :limits="limits"
      @update:params="onParamsChange"
      @reset="resetParams"
    />
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  height: 100%;
  min-height: 0;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #fbfbff 0%, var(--bg-page) 40%);
}

.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 26px;
  border-bottom: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(12px);
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.head-left h1 {
  font-size: 16px;
  font-weight: 600;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  padding: 3px 9px;
  border-radius: 8px;
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.09);
}

.model-chip.soft {
  color: #0891b2;
  background: rgba(34, 211, 238, 0.1);
}

.head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.param-btn {
  border-color: var(--border-color);
  color: var(--text-sub);
}

.param-btn:hover {
  color: var(--brand-1);
  border-color: rgba(99, 102, 241, 0.45);
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 26px 8px;
  scroll-behavior: smooth;
}

.message-list {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 12px;
}

.welcome {
  position: relative;
  max-width: 720px;
  margin: 6vh auto 0;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.welcome-glow {
  position: absolute;
  top: -60px;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.16), transparent 68%);
  filter: blur(10px);
  z-index: 0;
}

.welcome-icon {
  position: relative;
  width: 60px;
  height: 60px;
  border-radius: 20px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--gradient-brand);
  box-shadow: 0 16px 34px rgba(99, 102, 241, 0.32);
  animation: pulseSoft 4s ease-in-out infinite;
}

.welcome h2 {
  position: relative;
  font-size: 24px;
  letter-spacing: -0.5px;
}

.welcome p {
  position: relative;
  color: var(--text-muted);
  font-size: 13.5px;
}

.suggestions {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  width: 100%;
  margin-top: 22px;
}

.suggestion {
  position: relative;
  text-align: left;
  padding: 14px 16px 18px;
  border-radius: 16px;
  border: 1px solid var(--border-color);
  background: #fff;
  cursor: pointer;
  transition: all 0.25s ease;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suggestion:hover {
  transform: translateY(-3px);
  border-color: rgba(99, 102, 241, 0.35);
  box-shadow: 0 14px 30px rgba(28, 32, 48, 0.08);
}

.suggestion::after {
  content: '';
  position: absolute;
  inset: auto 0 0;
  height: 3px;
  background: var(--gradient-brand);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.3s ease;
}

.suggestion:hover::after {
  transform: scaleX(1);
}

.s-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-1);
}

.s-text {
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.6;
}

.s-arrow {
  position: absolute;
  right: 12px;
  bottom: 12px;
  color: #c7cbe0;
  transition: all 0.25s ease;
}

.suggestion:hover .s-arrow {
  color: var(--brand-1);
  transform: translateX(2px);
}

.composer {
  padding: 8px 26px 14px;
}

.composer-inner {
  max-width: 960px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  padding: 10px 12px 8px;
  box-shadow: 0 10px 30px rgba(28, 32, 48, 0.06);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.composer-inner:focus-within {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 12px 34px rgba(99, 102, 241, 0.14);
}

.composer-input :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  padding: 4px 6px;
  font-size: 14px;
  line-height: 1.7;
  background: transparent;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  padding-left: 6px;
}

.hint-line {
  font-size: 11.5px;
  color: var(--text-muted);
}

.send-btn {
  padding: 8px 18px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #fff;
}

.stop-btn {
  border-radius: 12px;
}

.disclaimer {
  max-width: 960px;
  margin: 8px auto 0;
  text-align: center;
  font-size: 11px;
  color: #b0b6c8;
}

@media (max-width: 980px) {
  .suggestions {
    grid-template-columns: 1fr;
  }

  .chat-head {
    padding: 12px 16px;
  }

  .messages,
  .composer {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
