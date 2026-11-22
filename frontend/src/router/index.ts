import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import InsightPublicationView from '@/views/InsightPublicationView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/insight_publication', name: 'insight_publication', component: InsightPublicationView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
