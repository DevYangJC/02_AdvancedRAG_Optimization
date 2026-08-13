/**
 * 路由与守卫:登录态 + admin 角色隔离。
 * 所有需要登录的页面都在全局守卫里拦截,未登录一律重定向到 /login 并带上原路径,
 * 登录成功后由登录页读 redirect 参数跳回,用户不会丢失本来要去的页面。
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  // createWebHistory 用 HTML5 History API:URL 干净无 # 号,但生产环境需 Nginx 回退 index.html。
  history: createWebHistory(),
  routes: [
    // 根路径直接进入聊天工作台,不单独做落地页。
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
      component: () => import('@/views/MainLayout.vue'),
      children: [
        {
          path: '',
          redirect: '/chat',
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/ChatView.vue'),
          meta: { title: '知识问答' },
        },
        {
          path: 'admin/knowledge',
          name: 'admin-knowledge',
          component: () => import('@/views/AdminKnowledgeView.vue'),
          meta: { title: '文档管理', adminOnly: true },
        },
      ],
    },
  ],
})

// 全局前置守卫:每次路由跳转前执行,集中处理三类拦截场景,避免每个页面各自判断。
router.beforeEach((to) => {
  const auth = useAuthStore()
  const loggedIn = !!auth.token
  // 1) 未登录访问受保护页 → 去登录页,并把目标路径记进 query 供登录后跳回。
  if (!to.meta.public && !loggedIn) return { path: '/login', query: { redirect: to.fullPath } }
  // 2) 已登录访问登录/注册页 → 直接进聊天页,避免"登录页一闪而过"的割裂感。
  if (to.meta.public && loggedIn) return { path: '/chat' }
  // 3) 普通用户访问 admin 专属页 → 静默送回聊天页,不暴露管理入口的存在。
  if (to.meta.adminOnly && !auth.isAdmin()) return { path: '/chat' }
  // 通过拦截后,把路由配置的 title 同步到浏览器标签页。
  document.title = to.meta.title ? `${to.meta.title} · 智能知识库` : '智能知识库'
  return true
})

export default router
