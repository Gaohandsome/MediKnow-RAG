import http from './http'

export const apiAuth = {
  captcha: () => http.get('/auth/captcha'),
  register: (data) => http.post('/auth/register', data),
  login: (data) => http.post('/auth/login', data),
  me: () => http.get('/auth/me'),
}

export const apiKb = {
  list: (params) => http.get('/knowledge-bases', { params }),
  options: () => http.get('/knowledge-bases/options'),
  create: (data) => http.post('/knowledge-bases', data),
  detail: (id) => http.get(`/knowledge-bases/${id}`),
  update: (id, data) => http.patch(`/knowledge-bases/${id}`, data),
  remove: (id) => http.delete(`/knowledge-bases/${id}`),
}

export const apiDoc = {
  list: (kbId) => http.get(`/knowledge-bases/${kbId}/documents`),
  upload: (kbId, formData, onProgress) =>
    http.post(`/knowledge-bases/${kbId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
      onUploadProgress: onProgress,
    }),
  detail: (id) => http.get(`/documents/${id}`),
  remove: (id) => http.delete(`/documents/${id}`),
  reindex: (id) => http.post(`/documents/${id}/reindex`),
  chunks: (id, params) => http.get(`/documents/${id}/chunks`, { params }),
  updateChunk: (chunkId, data) => http.patch(`/chunks/${chunkId}`, data),
  removeChunk: (chunkId) => http.delete(`/chunks/${chunkId}`),
}

export const apiChat = {
  models: () => http.get('/chat/models'),
  sessions: () => http.get('/chat/sessions'),
  createSession: (data) => http.post('/chat/sessions', data),
  updateSession: (id, data) => http.patch(`/chat/sessions/${id}`, data),
  removeSession: (id) => http.delete(`/chat/sessions/${id}`),
  messages: (id) => http.get(`/chat/sessions/${id}/messages`),
}

export const apiSystem = {
  safetyConfig: () => http.get('/system/safety-config'),
}
