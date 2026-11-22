"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class InsightPublishPayload(BaseModel):
    """洞察发布：目标项目、采样用途与本次申请的授权字段。"""

    project: str | None = None
    target_project: str | None = None
    authorized_fields: list[str] | str | None = None
    auth_fields: list[str] | str | None = None
    sampling_purpose: str = "普通取样"
    owner: str | None = None
    shared_project: bool = False
    auth_version: int | None = None
    source_name: str | None = None
    remark: str | None = None


class SampleRegistrationPayload(BaseModel):
    samples: list[dict[str, Any]] = Field(default_factory=list)


class SamplePayload(BaseModel):
    """取样/分群：可选指定来源，未指定时按发布版本读取。"""

    source_id: int | None = None
    field: str | None = None
    sampling_purpose: str = "普通取样"


class SourceSamplePayload(BaseModel):
    sampling_purpose: str = "普通取样"
    field: str | None = None


class ClusterPayload(BaseModel):
    field: str = "cluster_label"
    source_id: int | None = None

