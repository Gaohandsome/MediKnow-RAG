<script setup>
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
})
</script>

<template>
  <div class="auth-page">
    <!-- 动态光斑背景 -->
    <div class="blob blob-1"></div>
    <div class="blob blob-2"></div>
    <div class="blob blob-3"></div>

    <div class="auth-grid">
      <section class="auth-side fade-up">
        <BrandLogo :size="42" />
        <h1>
          院内知识，<br />
          <span class="gradient-text">问一句就有依据</span>
        </h1>
        <p class="desc">
          把诊疗规范、药品说明书、院内制度交给知识库，系统自动切块、向量化并混合检索，
          再由通义千问结合院内资料流式作答，每条结论都能回溯到原文。
        </p>

        <ul class="feature-list">
          <li>
            <span class="dot" style="background: #6366f1"></span>
            多格式解析：指南 PDF / 培训 PPT / 制度 Word / Markdown / 检查流程图
          </li>
          <li>
            <span class="dot" style="background: #8b5cf6"></span>
            bge-m3 稠密 + 稀疏混合检索，bge-reranker 精排
          </li>
          <li>
            <span class="dot" style="background: #22d3ee"></span>
            流式输出、多轮上下文、高危症状预警与免责声明
          </li>
        </ul>

        <div class="stat-row">
          <div class="stat">
            <strong>6</strong>
            <span>核心页面</span>
          </div>
          <div class="stat">
            <strong>1024</strong>
            <span>向量维度</span>
          </div>
          <div class="stat">
            <strong>SSE</strong>
            <span>流式回答</span>
          </div>
        </div>
      </section>

      <section class="auth-card fade-up" style="animation-delay: 0.08s">
        <header class="card-head">
          <h2>{{ title }}</h2>
          <p v-if="subtitle">{{ subtitle }}</p>
        </header>
        <slot />
      </section>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  position: relative;
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
  overflow: hidden;
  background: radial-gradient(1200px 600px at 10% 10%, #eef0ff 0%, transparent 55%),
    radial-gradient(900px 500px at 90% 90%, #eaf9ff 0%, transparent 55%), #f6f7fb;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  opacity: 0.55;
  animation: floatBlob 18s ease-in-out infinite;
}

.blob-1 {
  width: 420px;
  height: 420px;
  background: rgba(99, 102, 241, 0.35);
  top: -120px;
  left: -80px;
}

.blob-2 {
  width: 360px;
  height: 360px;
  background: rgba(139, 92, 246, 0.28);
  bottom: -120px;
  right: -60px;
  animation-delay: -6s;
}

.blob-3 {
  width: 260px;
  height: 260px;
  background: rgba(34, 211, 238, 0.25);
  top: 55%;
  left: 45%;
  animation-delay: -12s;
}

.auth-grid {
  position: relative;
  z-index: 1;
  width: min(1080px, 100%);
  display: grid;
  grid-template-columns: 1.1fr 460px;
  gap: 56px;
  align-items: center;
}

.auth-side h1 {
  margin: 28px 0 16px;
  font-size: 40px;
  line-height: 1.28;
  letter-spacing: -0.5px;
}

.desc {
  max-width: 460px;
  color: var(--text-sub);
  font-size: 14.5px;
  line-height: 1.85;
}

.feature-list {
  list-style: none;
  padding: 0;
  margin: 26px 0 0;
  display: grid;
  gap: 12px;
  color: var(--text-sub);
}

.feature-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13.5px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
}

.stat-row {
  display: flex;
  gap: 36px;
  margin-top: 40px;
}

.stat strong {
  display: block;
  font-size: 22px;
  letter-spacing: -0.5px;
}

.stat span {
  font-size: 12px;
  color: var(--text-muted);
}

.auth-card {
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(16px);
  border-radius: var(--radius-xl);
  border: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: var(--shadow-lg);
  padding: 38px 36px 32px;
}

.card-head h2 {
  font-size: 24px;
  letter-spacing: -0.4px;
}

.card-head p {
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 13px;
}

@media (max-width: 980px) {
  .auth-grid {
    grid-template-columns: 1fr;
    max-width: 440px;
  }

  .auth-side {
    display: none;
  }
}
</style>
