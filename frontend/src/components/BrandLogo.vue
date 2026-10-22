<script setup>
defineProps({
  size: { type: Number, default: 36 },
  showText: { type: Boolean, default: true },
})
</script>

<template>
  <div class="brand-logo">
    <div class="mark" :style="{ width: `${size}px`, height: `${size}px`, borderRadius: `${size * 0.3}px` }">
      <svg viewBox="0 0 32 32" :width="size * 0.62" :height="size * 0.62" fill="none">
        <path
          d="M8 11.5C8 9.6 9.6 8 11.5 8h9C22.4 8 24 9.6 24 11.5v5c0 1.9-1.6 3.5-3.5 3.5H15l-4.2 4v-4H11.5C9.6 21 8 19.4 8 17.5z"
          fill="white"
          fill-opacity="0.95"
        />
        <path d="M14.6 10.6h2.8v1.9h1.9v2.8h-1.9v1.9h-2.8v-1.9h-1.9v-2.8h1.9z" fill="#6366f1" />
      </svg>
    </div>
    <span v-if="showText" class="name">MediKnow<span class="dot">·</span><small>院内知识问答</small></span>
  </div>
</template>

<style scoped>
.brand-logo {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.mark {
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 60%, #a78bfa 100%);
  box-shadow: 0 10px 22px rgba(99, 102, 241, 0.32);
  transition: transform 0.3s ease;
}

.brand-logo:hover .mark {
  transform: rotate(-6deg) scale(1.04);
}

.name {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.2px;
  color: var(--text-main);
}

.dot {
  margin: 0 4px;
  color: var(--brand-2);
}

small {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: 0;
}
</style>
