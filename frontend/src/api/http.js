import axios from 'axios'
import { ElMessage } from 'element-plus'

export const TOKEN_KEY = 'rag_token'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 180000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) {
        return body.data
      }
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return body
  },
  (error) => {
    const status = error?.response?.status
    const message = error?.response?.data?.message || error?.message || '网络异常，请稍后重试'

    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (!window.location.pathname.startsWith('/login')) {
        ElMessage.warning('登录已失效，请重新登录')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }

    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export default http
