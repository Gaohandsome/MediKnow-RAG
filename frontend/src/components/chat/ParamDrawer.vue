<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  models: { type: Array, default: () => [] },
  params: { type: Object, required: true },
  limits: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update:modelValue', 'update:params', 'reset'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const presets = [
  { key: 'accurate', label: '精准', desc: '低温度', value: { temperature: 0.2, top_p: 0.6 } },
  { key: 'balance', label: '平衡', desc: '推荐', value: { temperature: 0.7, top_p: 0.8 } },
  { key: 'creative', label: '发散', desc: '高温度', value: { temperature: 1.1, top_p: 0.95 } },
]

function set(key, value) {
  emit('update:params', { ...props.params, [key]: value })
}

function applyPreset(preset) {
  emit('update:params', { ...props.params, ...preset.value })
}
</script>

<template>
  <el-drawer v-model="visible" title="推理与检索参数" size="392px" :with-header="true">
    <div class="drawer-body">
      <section class="section">
        <div class="section-title">大模型</div>
        <el-select :model-value="params.model" style="width: 100%" size="large" @change="(val) => set('model', val)">
          <el-option v-for="item in models" :key="item" :label="item" :value="item" />
        </el-select>
        <p class="hint">默认使用 qwen-max，参数仅在当前会话生效。</p>
      </section>

      <section class="section">
        <div class="section-title">快速预设</div>
        <div class="presets">
          <button
            v-for="preset in presets"
            :key="preset.key"
            type="button"
            class="preset"
            :class="{ active: Math.abs(params.temperature - preset.value.temperature) < 0.05 }"
            @click="applyPreset(preset)"
          >
            <strong>{{ preset.label }}</strong>
            <span>{{ preset.desc }}</span>
          </button>
        </div>
      </section>

      <section class="section">
        <div class="row">
          <span class="label">温度 temperature</span>
          <span class="value">{{ Number(params.temperature).toFixed(1) }}</span>
        </div>
        <el-slider
          :model-value="params.temperature"
          :min="0"
          :max="2"
          :step="0.1"
          @update:model-value="(val) => set('temperature', val)"
        />
        <p class="hint">值越低回答越稳定保守，越高越发散。</p>
      </section>

      <section class="section">
        <div class="row">
          <span class="label">top_p 核采样</span>
          <span class="value">{{ Number(params.top_p).toFixed(2) }}</span>
        </div>
        <el-slider
          :model-value="params.top_p"
          :min="0.05"
          :max="1"
          :step="0.05"
          @update:model-value="(val) => set('top_p', val)"
        />
      </section>

      <section class="section">
        <div class="row">
          <span class="label">最长输出 token</span>
          <el-input-number
            :model-value="params.max_tokens"
            :min="16"
            :max="8192"
            :step="128"
            size="small"
            controls-position="right"
            @update:model-value="(val) => set('max_tokens', val)"
          />
        </div>
      </section>

      <section class="section">
        <div class="row">
          <span class="label">历史对话轮数</span>
          <el-input-number
            :model-value="params.history_rounds"
            :min="0"
            :max="20"
            size="small"
            controls-position="right"
            @update:model-value="(val) => set('history_rounds', val)"
          />
        </div>
        <p class="hint">携带最近 {{ params.history_rounds }} 轮问答作为上下文，0 表示不携带历史。</p>
      </section>

      <div class="divider"></div>

      <section class="section">
        <div class="row">
          <span class="label">召回条数 top_k</span>
          <span class="value">{{ params.top_k }}</span>
        </div>
        <el-slider
          :model-value="params.top_k"
          :min="1"
          :max="20"
          :step="1"
          @update:model-value="(val) => set('top_k', val)"
        />
        <p class="hint">最终送入提示词的资料条数，越多上下文越充分但更耗 token。</p>
      </section>

      <section class="section">
        <div class="row">
          <span class="label">启用重排 reranker</span>
          <el-switch
            :model-value="params.use_rerank"
            @update:model-value="(val) => set('use_rerank', val)"
          />
        </div>
        <p class="hint">bge-reranker-v2-m3 交叉精排，可提升相关性，但会增加检索耗时。</p>
      </section>

      <div class="footer">
        <el-button @click="emit('reset')">恢复默认</el-button>
        <el-button type="primary" @click="visible = false">完成</el-button>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer-body {
  padding: 0 4px 20px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-main);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.label {
  font-size: 13px;
  color: var(--text-sub);
}

.value {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--brand-1);
  background: rgba(99, 102, 241, 0.1);
  padding: 1px 8px;
  border-radius: 7px;
}

.hint {
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.65;
  margin-top: 2px;
}

.presets {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.preset {
  padding: 10px 6px;
  border-radius: 12px;
  border: 1.5px solid var(--border-color);
  background: #fff;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.preset strong {
  font-size: 13px;
}

.preset span {
  font-size: 11px;
  color: var(--text-muted);
}

.preset:hover {
  border-color: rgba(99, 102, 241, 0.4);
}

.preset.active {
  border-color: var(--brand-1);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(139, 92, 246, 0.05));
}

.footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}
</style>
