// 应用入口:组装 Vue + Pinia + Router + Element Plus,再挂载到 #app 容器。
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
// 中文语言包:Element Plus 的组件文案(分页、弹窗按钮等)默认英文,必须显式切中文。
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
// 图标库整包注册:模板里直接用 <Edit />、<Delete />,无需在每个组件里逐个 import。
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)

// 依次安装:状态管理 → 路由 → UI 库;安装顺序不影响功能,固定下来便于排查问题。
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  // 图标注册名即组件名:例如 key 为 Edit 的组件,模板里直接写 <Edit />。
  app.component(key, component)
}

// 挂载到 index.html 的 #app 节点,之后所有路由页面都渲染在它内部。
app.mount('#app')
