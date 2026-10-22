<script setup>
import MarkdownIt from 'markdown-it'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useSafetyStore } from '@/stores/safety'

const props = defineProps({
  message: { type: Object, required: true },
  streaming: { type: Boolean, default: false },
  showDisclaimer: { type: Boolean, default: false },
})

const safetyStore = useSafetyStore()
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const showContexts = ref(false)

const isUser = computed(() => props.message.role === 'user')
const contexts = computed(() => props.message.contexts || [])
const rendered = computed(() => md.render(props.message.content || ''))
const isEmptyStreaming = computed(() => props.streaming && !props.message.content)
const safety = computed(() => props.message.safety || {})
const isRefused = computed(() => Boolean(safety.value.refusal))
const relevance = computed(() => {
  const first = contexts.value[0]
  const value = first?.relevance
  return typeof value === 'number' ? value.toFixed(2) : null
})
const safetyNotice = computed(() => safety.value.notice || '')

const INTENT_LABEL = {
  professional: '专业咨询',
  coding: '编程技术',
  general: '通用咨询',
  chitchat: '寒暄',
}
const STRATEGY_LABEL = {
  subquery: '子问题查询',
  backtrack: '回溯检索',
  hyde: '假设答案检索',
}

// 检索链路可视化：意图 → 策略 → 多路 → 缓存
const planChips = computed(() => {
  const plan = props.message.plan || {}
  const chips = []
  if (INTENT_LABEL[plan.intent]) chips.push({ text: INTENT_LABEL[plan.intent], kind: 'intent' })
  if (STRATEGY_LABEL[plan.strategy]) chips.push({ text: STRATEGY_LABEL[plan.strategy], kind: 'strategy' })
  const variants = plan.variants || []
  if (variants.length > 1) chips.push({ text: `多路召回 ${variants.length}`, kind: 'variant' })
  if (plan.cache_hit) {
    const score = Number(plan.cache_score)
    const suffix = Number.isFinite(score) && score < 1 ? ` ${score.toFixed(2)}` : ''
    chips.push({ text: `缓存命中${suffix}`, kind: 'cache' })
  }
  return chips
})
const showFooter = computed(
  () => !isUser.value && props.showDisclaimer && !props.streaming && Boolean(props.message.content)
    && safetyStore.disclaimerEnabled,
)

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content || '')
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}
</script>

<template>
  <div class="msg" :class="isUser ? 'user' : 'assistant'">
    <div class="avatar" :class="isUser ? 'user-avatar' : 'bot-avatar'">
      <el-icon v-if="!isUser" :size="17"><MagicStick /></el-icon>
      <span v-else>{{ message.userInitial || '我' }}</span>
    </div>

    <div class="body">
      <div v-if="!isUser" class="role-line">
        <span class="role">MediKnow 助手</span>
        <span v-if="isRefused" class="refused-chip">知识库未收录</span>
        <span v-if="message.latency_ms" class="latency">{{ (message.latency_ms / 1000).toFixed(1) }}s</span>
      </div>

      <div v-if="!isUser && planChips.length" class="plan-line">
        <span v-for="chip in planChips" :key="chip.text" class="plan-chip" :class="chip.kind">
          {{ chip.text }}
        </span>
      </div>

      <div v-if="!isUser && safetyNotice" class="safety-banner">
        <el-icon :size="15"><WarningFilled /></el-icon>
        <span>{{ safetyNotice }}</span>
      </div>

      <div class="bubble" :class="[isUser ? 'user-bubble' : 'bot-bubble', { 'refused-bubble': isRefused }]">
        <template v-if="isUser">
          <p class="plain">{{ message.content }}</p>
        </template>
        <template v-else>
          <div v-if="isEmptyStreaming" class="thinking">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            <span class="thinking-text">正在检索资料并组织答案…</span>
          </div>
          <div v-else class="markdown-body" v-html="rendered"></div>
          <span v-if="streaming && message.content" class="caret"></span>
        </template>
      </div>

      <div v-if="!isUser && contexts.length" class="contexts">
        <button class="ctx-toggle" type="button" @click="showContexts = !showContexts">
          <el-icon><Files /></el-icon>
          引用资料 {{ contexts.length }} 条
          <span v-if="relevance" class="ctx-relevance">相关度 {{ relevance }}</span>
          <el-icon class="chevron" :class="{ open: showContexts }"><ArrowDown /></el-icon>
        </button>

        <transition name="expand">
          <div v-show="showContexts" class="ctx-list">
            <div v-for="(item, index) in contexts" :key="item.chunk_id" class="ctx-item">
              <div class="ctx-head">
                <span class="ctx-index">[{{ index + 1 }}]</span>
                <span class="ctx-doc">{{ item.document_name }}</span>
                <span v-if="item.page > 0" class="ctx-page">第 {{ item.page }} 页</span>
                <span v-if="item.knowledge_base_name" class="ctx-kb">{{ item.knowledge_base_name }}</span>
                <span v-if="item.images && item.images.length" class="ctx-badge">
                  配图 {{ item.images.length }}
                </span>
              </div>
              <p class="ctx-content">{{ item.content }}</p>
              <div v-if="item.images && item.images.length" class="ctx-images">
                <el-image
                  v-for="(image, imageIndex) in item.images"
                  :key="image.url"
                  :src="image.url"
                  :preview-src-list="item.images.map((it) => it.url)"
                  :initial-index="imageIndex"
                  :title="image.caption"
                  fit="cover"
                  class="ctx-thumb"
                  preview-teleported
                >
                  <template #error>
                    <div class="ctx-thumb-fallback">图片不可用</div>
                  </template>
                </el-image>
              </div>
            </div>
          </div>
        </transition>
      </div>

      <div v-if="showFooter" class="msg-disclaimer">
        <el-icon :size="13"><InfoFilled /></el-icon>
        <span>{{ safetyStore.disclaimer }}</span>
      </div>

      <div v-if="!isUser && message.content && !streaming" class="actions">
        <el-button text size="small" @click="copyContent">
          <el-icon><CopyDocument /></el-icon>
          复制
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  gap: 12px;
  padding: 6px 0;
  animation: fadeUp 0.3s ease both;
}

.msg.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
  margin-top: 2px;
}

.bot-avatar {
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #a78bfa);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.28);
}

.user-avatar {
  color: #fff;
  background: linear-gradient(135deg, #0ea5e9, #22d3ee);
  box-shadow: 0 8px 18px rgba(14, 165, 233, 0.24);
}

.body {
  max-width: min(760px, 78%);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.msg.user .body {
  align-items: flex-end;
}

.role-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.role {
  font-weight: 600;
  color: var(--text-sub);
}

.latency {
  padding: 1px 7px;
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.08);
  color: var(--brand-1);
}

.bubble {
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}

.bot-bubble {
  background: #fff;
  border: 1px solid var(--border-color);
  border-top-left-radius: 6px;
  box-shadow: var(--shadow-sm);
}

.user-bubble {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  border-top-right-radius: 6px;
  box-shadow: 0 10px 24px rgba(99, 102, 241, 0.24);
}

.plain {
  white-space: pre-wrap;
}

.thinking {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 13px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand-2);
  animation: pulseSoft 1.2s ease-in-out infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

.thinking-text {
  margin-left: 4px;
}

.caret {
  display: inline-block;
  width: 2px;
  height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--brand-1);
  animation: blink 1s step-end infinite;
}

.contexts {
  margin-top: 2px;
}

.ctx-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: #fbfbfe;
  color: var(--text-sub);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.ctx-toggle:hover {
  border-color: rgba(99, 102, 241, 0.4);
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.05);
}

.chevron {
  transition: transform 0.2s ease;
  font-size: 11px;
}

.chevron.open {
  transform: rotate(180deg);
}

.ctx-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ctx-item {
  background: #fbfcff;
  border: 1px solid var(--border-color);
  border-left: 3px solid rgba(99, 102, 241, 0.5);
  border-radius: 10px;
  padding: 9px 12px;
}

.ctx-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.ctx-index {
  color: var(--brand-1);
  font-weight: 700;
}

.ctx-doc {
  color: var(--text-sub);
  font-weight: 500;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ctx-page {
  padding: 0 6px;
  border-radius: 5px;
  background: rgba(34, 211, 238, 0.12);
  color: #0891b2;
}

.ctx-relevance {
  padding: 0 6px;
  border-radius: 5px;
  background: rgba(99, 102, 241, 0.1);
  color: var(--brand-1);
}

.ctx-kb {
  margin-left: auto;
  color: var(--text-muted);
}

.ctx-content {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-sub);
  max-height: 96px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.ctx-badge {
  margin-left: auto;
  padding: 1px 7px;
  border-radius: 8px;
  background: rgba(99, 102, 241, 0.1);
  color: var(--brand-1);
  font-size: 11px;
}

.ctx-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.ctx-thumb {
  width: 132px;
  height: 92px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: #fff;
  cursor: zoom-in;
}

.ctx-thumb-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-size: 11px;
  color: var(--text-muted);
}

.actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.msg:hover .actions {
  opacity: 1;
}

.refused-chip {
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 11px;
  color: #92400e;
  background: rgba(245, 158, 11, 0.14);
}

.plan-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.plan-chip {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
  border: 1px solid transparent;
  white-space: nowrap;
}

.plan-chip.intent {
  color: #1d4ed8;
  background: rgba(59, 130, 246, 0.12);
}

.plan-chip.strategy {
  color: #6d28d9;
  background: rgba(139, 92, 246, 0.14);
}

.plan-chip.variant {
  color: #0f766e;
  background: rgba(20, 184, 166, 0.14);
}

.plan-chip.cache {
  color: #166534;
  background: rgba(34, 197, 94, 0.16);
}

.safety-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(217, 119, 6, 0.35);
  background: #fff8eb;
  color: #92400e;
  font-size: 12.5px;
  line-height: 1.7;
}

.safety-banner .el-icon {
  margin-top: 2px;
  color: #d97706;
  flex: 0 0 auto;
}

.refused-bubble {
  background: #fafafa;
  border-style: dashed;
  box-shadow: none;
}

.msg-disclaimer {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  padding: 0 4px;
  font-size: 11px;
  line-height: 1.6;
  color: #9aa1b4;
}

.msg-disclaimer .el-icon {
  margin-top: 1px;
  flex: 0 0 auto;
}

.expand-enter-active,
.expand-leave-active {
  transition: all 0.22s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
