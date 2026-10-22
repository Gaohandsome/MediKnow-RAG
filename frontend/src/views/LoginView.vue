<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AuthShell from '@/components/AuthShell.vue'
import CaptchaField from '@/components/CaptchaField.vue'
import { apiAuth } from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref()
const submitting = ref(false)
const captchaLoading = ref(false)
const captchaImage = ref('')
const captchaId = ref('')

const form = reactive({
  username: '',
  password: '',
  captcha_code: '',
})

const rules = {
  username: [{ required: true, message: '请输入账号名称', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  captcha_code: [{ required: true, message: '请输入图形验证码', trigger: 'blur' }],
}

async function loadCaptcha() {
  captchaLoading.value = true
  try {
    const data = await apiAuth.captcha()
    captchaId.value = data.captcha_id
    captchaImage.value = data.image
  } finally {
    captchaLoading.value = false
  }
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await authStore.login({
      username: form.username.trim(),
      password: form.password,
      captcha_id: captchaId.value,
      captcha_code: form.captcha_code.trim(),
    })
    ElMessage.success('登录成功，欢迎回来')
    const redirect = route.query.redirect
    router.replace(typeof redirect === 'string' && redirect ? redirect : '/chat')
  } catch {
    form.captcha_code = ''
    loadCaptcha()
  } finally {
    submitting.value = false
  }
}

onMounted(loadCaptcha)
</script>

<template>
  <AuthShell title="欢迎回来" subtitle="登录后即可管理院内知识库并开始提问">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large" @submit.prevent>
      <el-form-item label="账号名称" prop="username">
        <el-input v-model="form.username" placeholder="请输入账号名称" maxlength="32" autocomplete="username">
          <template #prefix>
            <el-icon><User /></el-icon>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          placeholder="请输入密码"
          show-password
          autocomplete="current-password"
          @keyup.enter="onSubmit"
        >
          <template #prefix>
            <el-icon><Lock /></el-icon>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item label="图形验证码" prop="captcha_code">
        <CaptchaField
          v-model="form.captcha_code"
          :image="captchaImage"
          :loading="captchaLoading"
          @refresh="loadCaptcha"
        />
      </el-form-item>

      <el-button class="submit-btn btn-gradient" size="large" :loading="submitting" @click="onSubmit">
        登 录
      </el-button>

      <div class="foot">
        <span class="muted">还没有账号？</span>
        <router-link class="link" to="/register">立即注册</router-link>
      </div>
    </el-form>
  </AuthShell>
</template>

<style scoped>
.submit-btn {
  width: 100%;
  margin-top: 6px;
  height: 44px;
  font-size: 15px;
  letter-spacing: 2px;
}

.foot {
  margin-top: 20px;
  text-align: center;
  font-size: 13px;
}

.link {
  margin-left: 6px;
  color: var(--brand-1);
  font-weight: 600;
}

.link:hover {
  text-decoration: underline;
}
</style>
