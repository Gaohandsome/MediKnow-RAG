import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { public: true, title: '注册' },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', redirect: '/chat' },
      {
        path: 'chat',
        name: 'chat',
        component: () => import('@/views/ChatView.vue'),
        meta: { title: '智能问答' },
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/views/KnowledgeListView.vue'),
        meta: { title: '知识库管理' },
      },
      {
        path: 'knowledge/:id',
        name: 'knowledge-detail',
        component: () => import('@/views/KnowledgeDetailView.vue'),
        meta: { title: '知识库详情' },
      },
      {
        path: 'knowledge/:id/upload',
        name: 'knowledge-upload',
        component: () => import('@/views/KnowledgeUploadView.vue'),
        meta: { title: '文档解析' },
      },
      {
        path: 'knowledge/:id/documents/:docId',
        name: 'document-preview',
        component: () => import('@/views/ChunkPreviewView.vue'),
        meta: { title: '知识预览' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const token = localStorage.getItem('rag_token')
  if (!to.meta.public && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.public && token && (to.name === 'login' || to.name === 'register')) {
    return { name: 'chat' }
  }
  document.title = to.meta.title ? `${to.meta.title} · MediKnow-RAG` : 'MediKnow-RAG · 院内知识库问答'
  return true
})

export default router
