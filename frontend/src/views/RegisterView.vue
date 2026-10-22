<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AuthShell from '@/components/AuthShell.vue'
import CaptchaField from '@/components/CaptchaField.vue'
import { apiAuth } from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref()
const submitting = ref(false)
const captchaLoading = ref(false)
const captchaImage = ref('')
const captchaId = ref('')

const form = reactive({
  username: '',
  password: '',
  confirm_password: '',
  captcha_code: '',
})

const validateConfirm = (_rule, value, callback) => {
  if (!value) {
    callback(new Error('请再次输入密码'))
  } else if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  username: [
    { required: true, message: '请输入账号名称', trigger: 'blur' },
    { min: 3, max: 32, message: '账号长度为 3~32 个字符', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9]+$/,
      message: '账号只能包含字母和数字',
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码长度为 6~64 个字符', trigger: 'blur' },
  ],
  confirm_password: [{ validator: validateConfirm, trigger: 'blur' }],
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
    await authStore.register({
      username: form.username.trim(),
      password: form.password,
      confirm_password: form.confirm_password,
      captcha_id: captchaId.value,
      captcha_code: form.captcha_code.trim(),
    })
    ElMessage.success('注册成功，请使用新账号登录')
    router.replace('/login')
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
  <AuthShell title="创建账号" subtitle="注册后即可创建知识库、上传文档并开始问答">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large" @submit.prevent>
      <el-form-item label="账号名称" prop="username">
        <el-input v-model="form.username" placeholder="字母或数字，3~32 位" maxlength="32">
          <template #prefix>
            <el-icon><User /></el-icon>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item label="密码" prop="password">
        <el-input v-model="form.password" type="password" placeholder="至少 6 位" show-password>
          <template #prefix>
            <el-icon><Lock /></el-icon>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item label="确认密码" prop="confirm_password">
        <el-input
          v-model="form.confirm_password"
          type="password"
          placeholder="请再次输入密码"
          show-password
          @keyup.enter="onSubmit"
        >
          <template #prefix>
            <el-icon><CircleCheck /></el-icon>
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
        注 册
      </el-button>

      <div class="foot">
        <span class="muted">已有账号？</span>
        <router-link class="link" to="/login">去登录</router-link>
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
