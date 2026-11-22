"""洞察发布与采样归档的领域接口。

这些动作跨「挖掘结果管理」和「特征源管理」两个模块，且固定路径段（publish、
sample、cluster、archives）会和通用资源路由的 `/{module}/{entry_id}` 抢匹配，
所以单独放在这里，并在 app 里优先于通用资源路由注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.routers.resource import require_service
from app.schemas import (
    ClusterPayload,
    InsightPublishPayload,
    SamplePayload,
    SampleRegistrationPayload,
    SourceSamplePayload,
)

router = APIRouter(prefix="/api", tags=["洞察发布"])


def _fields(payload: InsightPublishPayload):
    return (
        payload.authorized_fields
        if payload.authorized_fields is not None
        else payload.auth_fields
    )


# ── 挖掘结果侧：授权、发布、发布版本、取样归档 ──

@router.get("/mining_result/publications", response_model=dict)
def list_publications(
    project: str | None = Query(default=None),
    result_id: int | None = Query(default=None),
) -> dict[str, Any]:
    return require_service("mining_result").list_insight_publications(
        result_id=result_id, project=project)


@router.get("/mining_result/archives", response_model=dict)
def list_archives(
    publication_id: int | None = Query(default=None),
    source_id: int | None = Query(default=None),
    result_id: int | None = Query(default=None),
    field: str | None = Query(default=None),
) -> dict[str, Any]:
    return require_service("mining_result").list_sampling_archives(
        publication_id=publication_id, source_id=source_id,
        result_id=result_id, field=field,
    )


@router.get("/mining_result/archives/{archive_id}", response_model=dict)
def get_archive(archive_id: int) -> dict[str, Any]:
    from app.services.insight_publication import find_archive

    archive = find_archive(archive_id)
    if archive is None:
        raise HTTPException(status_code=404, detail=f"归档 {archive_id} 不存在")
    return archive


@router.get("/mining_result/archives/{archive_id}/trace", response_model=dict)
def trace_archive(archive_id: int) -> dict[str, Any]:
    return require_service("mining_result").trace_insight_version(archive_id=archive_id)


@router.get("/mining_result/trace", response_model=dict)
def trace_by_field(
    field: str = Query(...),
    source_id: int | None = Query(default=None),
    publication_id: int | None = Query(default=None),
) -> dict[str, Any]:
    return require_service("mining_result").trace_insight_version(
        field=field, source_id=source_id, publication_id=publication_id)


@router.get("/mining_result/projects/{project}/authorization", response_model=dict)
def get_project_authorization(project: str) -> dict[str, Any]:
    return require_service("mining_result").get_project_authorization(project)


@router.put("/mining_result/projects/{project}/authorization", response_model=dict)
def update_project_authorization(
    project: str,
    payload: InsightPublishPayload,
) -> dict[str, Any]:
    return require_service("mining_result").update_project_authorization(
        project,
        _fields(payload) or [],
        sampling_purpose=payload.sampling_purpose,
        shared_project=payload.shared_project,
        auth_version=payload.auth_version,
    )


@router.post("/mining_result/demo", response_model=dict)
def run_demo(
    project: str = Query(default="P"),
    result_id: int = Query(default=1),
) -> dict[str, Any]:
    return require_service("mining_result").run_publication_demo(
        project=project, result_id=result_id)


@router.post("/mining_result/publications/{publication_id}/sample", response_model=dict)
def sample_publication(publication_id: int, payload: SamplePayload) -> dict[str, Any]:
    return require_service("mining_result").sample_published_insight(
        publication_id, source_id=payload.source_id)


@router.post("/mining_result/publications/{publication_id}/cluster", response_model=dict)
def cluster_publication(publication_id: int, payload: ClusterPayload) -> dict[str, Any]:
    return require_service("mining_result").cluster_published_insight(
        publication_id, payload.field or "cluster_label", source_id=payload.source_id)


@router.post("/mining_result/{result_id}/samples", response_model=dict)
def register_samples(
    result_id: int,
    payload: SampleRegistrationPayload,
) -> dict[str, Any]:
    return require_service("mining_result").register_insight_samples(
        result_id, payload.samples)


@router.post("/mining_result/{result_id}/publish", response_model=dict)
def publish_insight(result_id: int, payload: InsightPublishPayload) -> dict[str, Any]:
    project = (payload.project or payload.target_project or "").strip()
    return require_service("mining_result").publish_insight(
        result_id,
        project,
        authorized_fields=_fields(payload),
        sampling_purpose=payload.sampling_purpose,
        owner=payload.owner,
        shared_project=payload.shared_project,
        auth_version=payload.auth_version,
        source_name=payload.source_name,
    )


@router.get("/mining_result/{result_id}/publications", response_model=dict)
def publications_of_insight(result_id: int) -> dict[str, Any]:
    return require_service("mining_result").list_insight_publications(result_id=result_id)


# ── 特征源侧：字段发现、取样、分群、历史归档 ──

@router.get("/feature_source/{source_id}/schema", response_model=dict)
def discover_source_fields(source_id: int) -> dict[str, Any]:
    return require_service("feature_source").fetch_source_schema(source_id)


@router.get("/feature_source/{source_id}/archives", response_model=dict)
def source_archives(source_id: int) -> dict[str, Any]:
    return require_service("feature_source").published_source_archive(source_id)


@router.post("/feature_source/{source_id}/sample", response_model=dict)
def sample_source(source_id: int, payload: SourceSamplePayload) -> dict[str, Any]:
    return require_service("feature_source").sample_published_source(
        source_id, sampling_purpose=payload.sampling_purpose, field=payload.field)


@router.post("/feature_source/{source_id}/cluster", response_model=dict)
def cluster_source(source_id: int, payload: ClusterPayload) -> dict[str, Any]:
    return require_service("feature_source").cluster_published_source(
        source_id, payload.field or "cluster_label")
