<script setup>
defineProps({
  modelValue: { type: String, default: '' },
  image: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'refresh'])
</script>

<template>
  <div class="captcha-row">
    <el-input
      :model-value="modelValue"
      placeholder="请输入验证码"
      maxlength="8"
      size="large"
      @update:model-value="(val) => emit('update:modelValue', val)"
    >
      <template #prefix>
        <el-icon><Key /></el-icon>
      </template>
    </el-input>

    <button type="button" class="captcha-img" :class="{ loading }" title="点击刷新验证码" @click="emit('refresh')">
      <img v-if="image" :src="image" alt="验证码" />
      <span v-else class="placeholder">加载中…</span>
      <span class="refresh-hint"><el-icon><Refresh /></el-icon></span>
    </button>
  </div>
</template>

<style scoped>
.captcha-row {
  display: grid;
  grid-template-columns: 1fr 132px;
  gap: 10px;
  align-items: center;
}

.captcha-img {
  position: relative;
  height: 40px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: #f7f9fd;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.captcha-img:hover {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15);
}

.captcha-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.captcha-img.loading img {
  opacity: 0.4;
}

.placeholder {
  font-size: 12px;
  color: var(--text-muted);
}

.refresh-hint {
  position: absolute;
  right: 4px;
  bottom: 2px;
  color: var(--brand-1);
  opacity: 0;
  transition: opacity 0.2s ease;
}

.captcha-img:hover .refresh-hint {
  opacity: 0.9;
}
</style>
