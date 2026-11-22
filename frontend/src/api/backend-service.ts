import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// ── 洞察发布 / 字段授权 / 采样归档 ──
// 返回结构保留后端的三层信息：发布版本（项目、归属、授权版本）、获准采样
// 字段清单、以及按字段回查洞察版本用的归档来源。

export type PublicationRecord = {
  publication_id: number
  publication_version: number
  result_id: number
  insight_version: string
  project: string
  owner: string
  shared_project: boolean
  auth_version: number
  approved_fields: string[]
  requested_fields?: string[]
  unauthorized_fields?: string[]
  sampling_purpose: string
  sample_snapshot?: Record<string, unknown>[]
}

export type SamplingArchive = {
  archive_id: number
  publication_id: number
  publication_version: number
  result_id: number
  insight_id: number
  insight_version: string
  project: string
  owner: string
  auth_version: number
  fields_used: string[]
  field_sources: Record<string, Record<string, unknown>>
  sample_count: number
  null_rate: Record<string, number>
  cluster_stats?: { field: string; counts: Record<string, number> }
}

export type PublishResult = PublicationRecord & {
  ok: boolean
  error?: string
  message: string
  source_id: number
  source?: Record<string, unknown>
  publication?: PublicationRecord
}

export type SampleResult = {
  ok: boolean
  error?: string
  message: string
  publication_id: number
  project: string
  insight_version: string
  auth_version: number
  approved_fields: string[]
  fields_used: string[]
  field_sources: Record<string, Record<string, unknown>>
  sample_count: number
  samples: Record<string, unknown>[]
  null_rate: Record<string, number>
  archive_id: number
  archive: SamplingArchive
}

export type ClusterResult = {
  ok: boolean
  allowed?: boolean
  error?: string
  message: string
  publication_id: number
  auth_version: number
  approved_fields: string[]
  groups?: Record<string, number>
}

export async function publishInsight(
  resultId: number,
  payload: {
    project: string
    authorized_fields?: string[]
    sampling_purpose?: string
    owner?: string
    shared_project?: boolean
  },
): Promise<PublishResult> {
  const response = await request(`/api/mining_result/${resultId}/publish`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function listPublications(
  resultId?: number,
  project?: string,
): Promise<{ ok: boolean; items: PublicationRecord[]; total: number }> {
  const query = new URLSearchParams()
  if (resultId !== undefined) query.set('result_id', String(resultId))
  if (project) query.set('project', project)
  const response = await request(`/api/mining_result/publications?${query.toString()}`)
  return await response.json()
}

export async function samplePublication(
  publicationId: number,
  sourceId?: number,
): Promise<SampleResult> {
  const response = await request(`/api/mining_result/publications/${publicationId}/sample`, {
    method: 'POST',
    body: JSON.stringify({ source_id: sourceId ?? null }),
  })
  return await response.json()
}

export async function clusterPublication(
  publicationId: number,
  sourceId?: number,
): Promise<ClusterResult> {
  const response = await request(`/api/mining_result/publications/${publicationId}/cluster`, {
    method: 'POST',
    body: JSON.stringify({ source_id: sourceId ?? null, field: 'cluster_label' }),
  })
  return await response.json()
}

export async function listArchives(params: {
  sourceId?: number
  publicationId?: number
  field?: string
}): Promise<{ ok: boolean; items: SamplingArchive[]; total: number }> {
  const query = new URLSearchParams()
  if (params.sourceId !== undefined) query.set('source_id', String(params.sourceId))
  if (params.publicationId !== undefined) query.set('publication_id', String(params.publicationId))
  if (params.field) query.set('field', params.field)
  const response = await request(`/api/mining_result/archives?${query.toString()}`)
  return await response.json()
}

export async function traceInsightVersion(archiveId: number): Promise<{
  ok: boolean
  insight_version: string
  publication_id: number
  fields_used: string[]
}> {
  const response = await request(`/api/mining_result/archives/${archiveId}/trace`)
  return await response.json()
}
