<template>
  <section class="page" data-testid="insight-publication">
    <header class="page-head">
      <div>
        <h2>洞察发布与字段授权</h2>
        <p class="page-desc">
          发布时按目标项目和采样用途校验字段权限，冻结获准采样字段清单；特征源取样与分群只认发布版本。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="load" type="button" @click="reload">刷新发布记录</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">发布版本</span>
        <strong class="stat-value">{{ publications.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">采样归档</span>
        <strong class="stat-value">{{ archives.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">当前授权版本</span>
        <strong class="stat-value">{{ lastAuthVersion }}</strong>
      </article>
    </div>

    <form class="analysis-form" data-testid="publish-form" @submit.prevent="submitPublish">
      <label>
        <span>洞察编号</span>
        <input v-model.number="form.resultId" data-testid="form-result" type="number" min="1" required />
      </label>
      <label>
        <span>目标项目</span>
        <input v-model="form.project" data-testid="form-project" required placeholder="例如 P" />
      </label>
      <label>
        <span>采样用途</span>
        <select v-model="form.purpose" data-testid="form-purpose">
          <option value="普通取样">普通取样</option>
          <option value="分群">分群</option>
        </select>
      </label>
      <label>
        <span>洞察归属</span>
        <input v-model="form.owner" data-testid="form-owner" placeholder="默认取洞察归属" />
      </label>
      <label class="field-check">
        <input v-model="form.shared" data-testid="form-shared" type="checkbox" />
        <span>共享项目</span>
      </label>
      <fieldset class="field-group">
        <legend>本次申请授权的字段</legend>
        <label v-for="field in allFields" :key="field">
          <input v-model="form.fields" :value="field" data-testid="form-field" type="checkbox" />
          <span>{{ field }}</span>
        </label>
      </fieldset>
      <button class="btn primary" data-testid="submit-publish" type="submit">发布洞察</button>
    </form>

    <p v-if="message" class="status-legend" :class="{ 'error-text': hasError }" data-testid="message">
      {{ message }}
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th>发布版本</th><th>目标项目</th><th>洞察版本</th><th>授权版本</th>
          <th>获准采样字段</th><th>洞察归属</th><th>共享项目</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in publications" :key="item.publication_id" :data-testid="`pub-${item.publication_id}`">
          <td>#{{ item.publication_id }} / v{{ item.publication_version }}</td>
          <td>{{ item.project }}</td>
          <td>{{ item.insight_version }}</td>
          <td>v{{ item.auth_version }}</td>
          <td>{{ item.approved_fields.join(',') || '—' }}</td>
          <td>{{ item.owner }}</td>
          <td>{{ item.shared_project ? '是' : '否' }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`sample-${item.publication_id}`" @click="sample(item)">
              普通取样
            </button>
            <button class="link" type="button" :data-testid="`cluster-${item.publication_id}`" @click="cluster(item)">
              按分群取样
            </button>
            <button class="link" type="button" :data-testid="`archives-${item.publication_id}`" @click="loadArchives(item)">
              查看归档
            </button>
          </td>
        </tr>
        <tr v-if="!publications.length">
          <td colspan="8" class="empty-state">暂无发布记录，先在上方发布一条洞察</td>
        </tr>
      </tbody>
    </table>

    <section v-if="activeSample" class="analysis-card" data-testid="sample-result">
      <h3>取样结果（发布 {{ activeSample.publication_id }}）</h3>
      <p>参考样本 {{ activeSample.sample_count }} 条，使用字段：{{ activeSample.fields_used.join(',') }}</p>
      <p>confidence 空值率：{{ rateText(activeSample.null_rate.confidence) }}</p>
      <table class="data-table">
        <thead><tr><th v-for="field in activeSample.fields_used" :key="field">{{ field }}</th></tr></thead>
        <tbody>
          <tr v-for="(sample, index) in activeSample.samples" :key="index">
            <td v-for="field in activeSample.fields_used" :key="field">{{ sample[field] ?? '空' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="page-desc">
        归档字段来源：{{ Object.keys(activeSample.field_sources).join(',') }}；按 confidence 回查洞察版本：
        <strong>{{ tracedVersion || '—' }}</strong>
      </p>
    </section>

    <section v-if="activeCluster" class="analysis-card" data-testid="cluster-result">
      <h3>分群结果（发布 {{ activeCluster.publication_id }}）</h3>
      <p v-if="activeCluster.ok">
        已按 {{ activeCluster.approved_fields.join(',') }} 分群：A={{ activeCluster.groups?.A ?? 0 }}，B={{ activeCluster.groups?.B ?? 0 }}
      </p>
      <p v-else class="error-text">分群被拒绝：{{ activeCluster.message }}</p>
    </section>

    <section v-if="archives.length" data-testid="archive-list">
      <h3>采样归档</h3>
      <table class="data-table">
        <thead>
          <tr><th>归档</th><th>发布版本</th><th>统计字段</th><th>样本数</th><th>空值率</th><th>洞察版本</th><th>分群统计</th></tr>
        </thead>
        <tbody>
          <tr v-for="archive in archives" :key="archive.archive_id" :data-testid="`archive-${archive.archive_id}`">
            <td>#{{ archive.archive_id }}</td>
            <td>#{{ archive.publication_id }} / v{{ archive.publication_version }}</td>
            <td>{{ archive.fields_used.join(',') }}</td>
            <td>{{ archive.sample_count }}</td>
            <td>{{ nullRateText(archive.null_rate) }}</td>
            <td>{{ archive.insight_version }}</td>
            <td>{{ archive.cluster_stats ? '有' : '无' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>字段授权按“目标项目 + 采样用途”生效，历史归档按原发布版本读取。</span>
      <span v-if="hasError" class="error-text">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  clusterPublication,
  listArchives,
  listPublications,
  publishInsight,
  samplePublication,
  traceInsightVersion,
} from '@/api/backend-service'
import type { ClusterResult, PublicationRecord, SampleResult, SamplingArchive } from '@/api/backend-service'

const allFields = ['confidence', 'cluster_label', 'insight_score']
const publications = ref<PublicationRecord[]>([])
const archives = ref<SamplingArchive[]>([])
const activeSample = ref<SampleResult | null>(null)
const activeCluster = ref<ClusterResult | null>(null)
const tracedVersion = ref('')
const message = ref('')
const hasError = ref(false)
const form = reactive({
  resultId: 1,
  project: 'P',
  purpose: '普通取样',
  owner: '',
  shared: false,
  fields: ['confidence'] as string[],
})

const lastAuthVersion = computed(() =>
  publications.value.reduce((max, item) => Math.max(max, item.auth_version), 0),
)

function rateText(rate: number | undefined) {
  if (rate === undefined) return '—'
  return `${rate.toFixed(4)}（${Math.round(rate * 1000) / 10}%）`
}

function nullRateText(rates: Record<string, number>) {
  return Object.entries(rates)
    .map(([field, rate]) => `${field}:${rate.toFixed(4)}`)
    .join('，')
}

async function reload() {
  hasError.value = false
  try {
    const payload = await listPublications()
    publications.value = payload.items
  } catch (error) {
    hasError.value = true
    message.value = error instanceof Error ? error.message : '发布记录读取失败'
  }
}

async function submitPublish() {
  hasError.value = false
  message.value = ''
  try {
    const result = await publishInsight(form.resultId, {
      project: form.project,
      authorized_fields: form.fields,
      sampling_purpose: form.purpose,
      owner: form.owner || undefined,
      shared_project: form.shared,
    })
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await reload()
  } catch (error) {
    hasError.value = true
    message.value = error instanceof Error ? error.message : '发布失败'
  }
}

async function sample(item: PublicationRecord) {
  hasError.value = false
  activeCluster.value = null
  try {
    const result = await samplePublication(item.publication_id)
    if (!result.ok) throw new Error(result.message)
    activeSample.value = result
    const trace = await traceInsightVersion(result.archive_id)
    tracedVersion.value = trace.ok ? trace.insight_version : ''
    await loadArchives(item)
  } catch (error) {
    hasError.value = true
    message.value = error instanceof Error ? error.message : '取样失败'
  }
}

async function cluster(item: PublicationRecord) {
  hasError.value = false
  try {
    activeCluster.value = await clusterPublication(item.publication_id)
  } catch (error) {
    hasError.value = true
    message.value = error instanceof Error ? error.message : '分群失败'
  }
}

async function loadArchives(item?: PublicationRecord) {
  try {
    const payload = await listArchives(
      item ? { publicationId: item.publication_id } : {},
    )
    archives.value = payload.items
  } catch (error) {
    hasError.value = true
    message.value = error instanceof Error ? error.message : '归档读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.field-check,
.field-group label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
}
.field-group {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  display: flex;
  gap: 12px;
}
.field-group legend {
  font-size: 12px;
  color: var(--muted);
}
.analysis-card {
  margin: 12px 0;
}
</style>
