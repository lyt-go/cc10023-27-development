"""洞察发布、字段授权与采样归档。

挖掘结果（洞察）只有在目标项目完成字段授权后才能被发布成特征源。发布时会把
目标项目、洞察归属、授权版本和获准采样字段一起冻结到发布记录里；之后特征源
的字段发现、取样和分群都只认这份冻结的版本，项目后续扩权不会反向改变历史
来源与历史归档。

本模块只依赖内存仓库，供 ``mining_result`` 与 ``feature_source`` 两个领域服务
共同调用，避免两边各写一套授权判断。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.store import store

# ── 仓库表名 ──
SAMPLE_MODULE = "insight_sample"
PUBLICATION_MODULE = "insight_publication"
ARCHIVE_MODULE = "insight_sampling_archive"
AUTHORIZATION_MODULE = "project_authorization"

# 洞察里可以对外发布的字段。真实项目里这些字段由洞察产出 schema 决定，
# 这里保留三个示例字段，保证只有 confidence 的项目也能完成普通取样。
KNOWN_FIELDS = ("confidence", "cluster_label", "insight_score")

FIELD_ALIASES: dict[str, str] = {
    "confidence": "confidence",
    "confidence_score": "confidence",
    "置信度": "confidence",
    "cluster_label": "cluster_label",
    "clusterlabel": "cluster_label",
    "cluster": "cluster_label",
    "cluster_id": "cluster_label",
    "group": "cluster_label",
    "label": "cluster_label",
    "分群": "cluster_label",
    "群组": "cluster_label",
    "关键分群": "cluster_label",
    "insight_score": "insight_score",
    "洞察分": "insight_score",
    "洞察得分": "insight_score",
}

CLUSTER_FIELD = "cluster_label"
CLUSTER_FIELD_ALIASES = {"cluster_label", "cluster", "cluster_id", "group", "label",
                         "分群", "群组", "关键分群"}
ORDINARY_SAMPLING_PURPOSES = {"普通取样", "普通采样", "ordinary", "sample", "sampling", "default"}
CLUSTER_SAMPLING_PURPOSES = {"分群", "聚类", "cluster", "cluster_sampling", "cluster_sample"}
PURPOSE_ALIASES = {
    **{purpose: "普通取样" for purpose in ORDINARY_SAMPLING_PURPOSES},
    **{purpose: "分群" for purpose in CLUSTER_SAMPLING_PURPOSES},
}
DEFAULT_PURPOSE = "普通取样"


def normalize_purpose(purpose: str | None) -> str:
    """把采样用途收敛成“普通取样 / 分群”两种，未知用途按普通取样处理。"""
    raw = str(purpose or "").strip()
    return PURPOSE_ALIASES.get(raw.casefold(), PURPOSE_ALIASES.get(raw, raw or DEFAULT_PURPOSE))



def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_field(field: str) -> str:
    """把中英文别名收敛到稳定的字段名。"""
    raw = str(field or "").strip()
    return FIELD_ALIASES.get(raw.casefold(), FIELD_ALIASES.get(raw, raw))


def normalize_fields(value: Any) -> list[str]:
    """接受逗号串、列表、字典等多种字段清单写法，输出去重后的字段列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        raw_items: Iterable[Any] = value.replace("，", ",").replace("、", ",").split(",")
    elif isinstance(value, dict):
        if "fields" in value:
            return normalize_fields(value.get("fields"))
        if "authorized_fields" in value:
            return normalize_fields(value.get("authorized_fields"))
        if "approved_fields" in value:
            return normalize_fields(value.get("approved_fields"))
        raw_items = [key for key, granted in value.items() if granted]
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]
    fields: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            item = item.get("field") or item.get("name") or item.get("字段") or ""
        normalized = normalize_field(str(item))
        if normalized and normalized not in fields:
            fields.append(normalized)
    return fields


def _sample_value(sample: dict[str, Any], field: str) -> Any:
    canonical = normalize_field(field)
    if canonical in sample:
        return sample.get(canonical)
    for key, value in sample.items():
        if normalize_field(str(key)) == canonical:
            return value
    return None


def _is_null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().casefold() in ("", "null", "none", "nan"))


# ── 洞察样本 ──
def register_insight_samples(result_id: int, samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """登记洞察样本，重复登记时按洞察整体替换，避免历史样本混入新版本。"""
    rows = store.rows(SAMPLE_MODULE)
    rows[:] = [
        row for row in rows
        if _int(row.get("result_id", row.get("insight_id", -1)), -1) != int(result_id)
    ]
    created: list[dict[str, Any]] = []
    for raw in samples:
        sample = dict(raw)
        sample["id"] = _next_id(rows)
        sample["result_id"] = int(result_id)
        sample["insight_id"] = int(result_id)
        for key, value in list(raw.items()):
            canonical = normalize_field(str(key))
            if canonical in KNOWN_FIELDS and canonical not in sample:
                sample[canonical] = value
        rows.append(sample)
        created.append(sample)
    return {"ok": True, "result_id": int(result_id), "sample_count": len(created), "samples": created}


def insight_samples(result_id: int) -> list[dict[str, Any]]:
    rows = store.rows(SAMPLE_MODULE)
    matched = [
        dict(row) for row in rows
        if _int(row.get("result_id", row.get("insight_id", -1)), -1) == int(result_id)
    ]
    if matched:
        return matched
    result = store.find("mining_result", int(result_id))
    if result is None:
        return []
    embedded = result.get("洞察样本") or result.get("样本") or result.get("samples")
    if isinstance(embedded, list):
        return [dict(item) for item in embedded if isinstance(item, dict)]
    # 洞察行本身就是一条样本时也允许直接取样。
    if any(normalize_field(str(key)) in KNOWN_FIELDS for key in result):
        return [dict(result)]
    return []


def available_fields(result_id: int) -> list[str]:
    """洞察可供发布的字段，按 KNOWN_FIELDS 的固定顺序返回。"""
    samples = insight_samples(result_id)
    found: list[str] = []
    for sample in samples:
        for key in sample:
            canonical = normalize_field(str(key))
            if canonical in KNOWN_FIELDS and canonical not in found:
                found.append(canonical)
    if not found:
        found = list(KNOWN_FIELDS)
    return [field for field in KNOWN_FIELDS if field in found]


# ── 项目字段授权 ──
def project_authorization(project: str) -> dict[str, Any] | None:
    for row in store.rows(AUTHORIZATION_MODULE):
        if str(row.get("project", row.get("目标项目", ""))) == str(project):
            return row
    return None


def _purpose_grant(row: dict[str, Any], purpose: str) -> list[str]:
    """读取项目在某个采样用途下的授权字段。

    项目登记了用途矩阵后严格按用途读取：普通取样拿不到只在分群用途下授权的
    cluster_label，避免“扩权分群”顺带放大普通取样。只有完全没有用途矩阵的
    历史记录才回退到整体授权。发布记录一旦生成就冻结字段清单，回退也不会让
    旧来源越过原发布版本的授权。
    """
    grants = row.get("grants")
    if isinstance(grants, dict) and grants:
        canonical = normalize_purpose(purpose)
        for key, values in grants.items():
            if normalize_purpose(str(key)) == canonical:
                return normalize_fields(values)
        return []
    return normalize_fields(row.get("authorized_fields", row.get("授权字段")))


def _store_purpose_grant(row: dict[str, Any], purpose: str, fields: list[str]) -> None:
    grants = row.get("grants")
    if not isinstance(grants, dict):
        grants = {}
    canonical = normalize_purpose(purpose)
    grants[canonical] = list(fields)
    row["grants"] = grants
    row["授权矩阵"] = {key: list(value) for key, value in grants.items()}
    union: list[str] = []
    for values in grants.values():
        for value in normalize_fields(values):
            if value not in union:
                union.append(value)
    row["authorized_fields"] = union
    row["授权字段"] = ",".join(union)


def current_project_fields(project: str, purpose: str = DEFAULT_PURPOSE) -> tuple[list[str], int]:
    row = project_authorization(project)
    if row is None:
        return [], 0
    return _purpose_grant(row, purpose), _int(
        row.get("auth_version", row.get("授权版本")), 1
    )


def update_project_authorization(
    project: str,
    fields: Any,
    *,
    sampling_purpose: str | None = None,
    auth_version: int | None = None,
    shared_project: bool | None = None,
) -> dict[str, Any]:
    """更新目标项目在某个采样用途下的字段授权；授权内容变化时版本自动递增。"""
    rows = store.rows(AUTHORIZATION_MODULE)
    purpose = normalize_purpose(sampling_purpose)
    authorized = normalize_fields(fields)
    row = project_authorization(str(project))
    if row is None:
        row = {
            "id": _next_id(rows),
            "project": str(project),
            "目标项目": str(project),
            "auth_version": 1,
            "授权版本": 1,
            "authorized_fields": [],
            "授权字段": "",
            "sampling_purpose": purpose,
            "采样用途": purpose,
            "shared_project": bool(shared_project),
            "共享项目": bool(shared_project),
            "updated_at": _now(),
        }
        rows.append(row)
        _store_purpose_grant(row, purpose, authorized)
        return row

    previous = _purpose_grant(row, purpose)
    changed = previous != authorized
    if auth_version is not None:
        version = int(auth_version)
    elif changed:
        version = _int(row.get("auth_version", row.get("授权版本")), 0) + 1
    else:
        version = _int(row.get("auth_version", row.get("授权版本")), 1)
    _store_purpose_grant(row, purpose, authorized)
    row["auth_version"] = version
    row["授权版本"] = version
    row["updated_at"] = _now()
    row["sampling_purpose"] = purpose
    row["采样用途"] = purpose
    if shared_project is not None:
        row["shared_project"] = bool(shared_project)
        row["共享项目"] = bool(shared_project)
    return row


# ── 发布 ──
def publish(
    result_id: int,
    project: str,
    *,
    authorized_fields: Any = None,
    sampling_purpose: str = "普通取样",
    owner: str | None = None,
    shared_project: bool = False,
    auth_version: int | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """把洞察发布给目标项目，冻结授权快照并生成可采样的特征源。

    只授权 confidence 时同样可以发布成功，只是发布版本里没有 cluster_label，
    后续任何分群请求都会在发布版本这一层被拒绝。
    """
    result_id = int(result_id)
    result = store.find("mining_result", result_id)
    if result is None:
        return {"ok": False, "message": f"挖掘结果 {result_id} 不存在", "error": "insight_not_found"}

    project = str(project or "").strip()
    if not project:
        return {"ok": False, "message": "发布时必须指定目标项目", "error": "project_required"}

    requested_given = normalize_fields(authorized_fields)
    insight_fields = available_fields(result_id)
    authorization = project_authorization(project)

    if authorization is None:
        # 项目还没有任何授权记录：只允许以最小权限 confidence 建档发布，保证
        # “只有 confidence 也能发布并做普通采样”。其他字段必须先走授权接口。
        if any(field != "confidence" for field in requested_given):
            return {
                "ok": False,
                "error": "project_not_authorized",
                "message": (
                    f"项目 {project} 尚未授权字段 "
                    f"{','.join(field for field in requested_given if field != 'confidence')}，"
                    f"请先完成字段授权再发布"
                ),
                "project": project,
                "target_project": project,
                "requested_fields": requested_given,
            }
        authorization = update_project_authorization(
            project,
            requested_given or ["confidence"],
            sampling_purpose=sampling_purpose,
            auth_version=auth_version,
            shared_project=shared_project,
        )
    granted_fields = _purpose_grant(authorization, sampling_purpose)
    version = _int(authorization.get("auth_version", authorization.get("授权版本")), 1)

    # 没有显式申请字段时按“项目授权 ∩ 洞察字段”发布，剩下的字段不进入本版本。
    requested = requested_given or [
        field for field in insight_fields if field in granted_fields
    ]
    approved_fields = [
        field for field in insight_fields
        if field in requested and field in granted_fields
    ]
    unauthorized_fields = [field for field in requested if field not in granted_fields]
    unavailable_fields = [
        field for field in requested
        if field in granted_fields and field not in insight_fields
    ]
    not_granted_fields = [field for field in insight_fields if field not in granted_fields]

    # 显式申请的字段必须全部通过授权检查；否则整次发布拒绝，不生成任何版本。
    blocking = (unauthorized_fields + unavailable_fields) if requested_given else []
    if not approved_fields or blocking:
        if not approved_fields:
            return {
                "ok": False,
                "error": "no_authorized_fields",
                "message": (
                    f"项目 {project} 在用途「{normalize_purpose(sampling_purpose)}」下没有可"
                    f"用于本洞察的授权字段，拒绝发布"
                ),
                "project": project,
                "target_project": project,
                "sampling_purpose": normalize_purpose(sampling_purpose),
                "auth_version": version,
                "authorized_fields": list(granted_fields),
                "requested_fields": requested,
                "unauthorized_fields": unauthorized_fields,
                "unavailable_fields": unavailable_fields,
            }
        return {
            "ok": False,
            "error": "field_not_authorized",
            "message": (
                f"项目 {project} 在用途「{normalize_purpose(sampling_purpose)}」下未授权字段 "
                f"{','.join(blocking)}，拒绝发布"
            ),
            "project": project,
            "target_project": project,
            "sampling_purpose": normalize_purpose(sampling_purpose),
            "auth_version": version,
            "authorized_fields": list(granted_fields),
            "requested_fields": requested,
            "unauthorized_fields": unauthorized_fields,
            "unavailable_fields": unavailable_fields,
        }

    owner_value = (
        owner
        if owner is not None
        else result.get("洞察归属")
        or result.get("归属项目")
        or result.get("owner")
        or project
    )
    shared_value = bool(
        shared_project
        or (authorization.get("shared_project") if authorization else False)
    )
    insight_version = str(
        result.get("洞察版本")
        or result.get("结果版本")
        or result.get("版本")
        or "v1.0.0"
    )

    publication_rows = store.rows(PUBLICATION_MODULE)
    publication_id = _next_id(publication_rows)
    # 同一洞察对同一项目的多次发布给出递增的发布版本，便于旧来源按原版本回查。
    version_for_pair = sum(
        1 for row in publication_rows
        if _int(row.get("result_id", row.get("insight_id", -1)), -1) == result_id
        and str(row.get("project", row.get("目标项目", ""))) == project
    ) + 1
    publication = {
        "id": publication_id,
        "publication_id": publication_id,
        "publication_version": version_for_pair,
        "发布版本": version_for_pair,
        "result_id": result_id,
        "insight_id": result_id,
        "insight_version": insight_version,
        "洞察版本": insight_version,
        "project": project,
        "target_project": project,
        "目标项目": project,
        "owner": owner_value,
        "insight_owner": owner_value,
        "洞察归属": owner_value,
        "shared_project": shared_value,
        "共享项目": shared_value,
        "auth_version": version,
        "授权版本": version,
        "authorized_fields": list(granted_fields),
        "授权字段": ",".join(granted_fields),
        "approved_fields": list(approved_fields),
        "sampling_fields": list(approved_fields),
        "获准采样字段清单": ",".join(approved_fields),
        "sampling_purpose": normalize_purpose(sampling_purpose),
        "采样用途": normalize_purpose(sampling_purpose),
        "requested_fields": requested,
        "unauthorized_fields": unauthorized_fields,
        "unavailable_fields": unavailable_fields,
        "not_granted_fields": not_granted_fields,
        # 冻结发布时的参考样本：之后洞察继续演进，旧来源与旧归档仍按本版本读取。
        "sample_snapshot": [dict(item) for item in insight_samples(result_id)],
        "published_at": _now(),
        "status": "已发布",
    }
    publication_rows.append(publication)

    # 发布同时生成特征源。源上冗余保存发布快照，后续字段发现与取样不再读取
    # 项目当前授权，而是读取这里的 publication_id。
    source_rows = store.rows("feature_source")
    source_id = _next_id(source_rows)
    source = {
        "id": source_id,
        "status": "已接入",
        "pending": False,
        "abnormal": False,
        "源编号": f"SRC-PUB-{publication_id:04d}",
        "源名称": source_name or f"洞察发布_{result_id}_{project}",
        "数据表名": f"insight_published_{publication_id}",
        "连接配置": "hive_metastore_host",
        "字段清单": ",".join(approved_fields),
        "采样比例": "1.0",
        "缓存策略": "memory_1h",
        "源版本": f"v{version_for_pair}.0.0",
        "publication_id": publication_id,
        "发布编号": publication_id,
        "publication_version": version_for_pair,
        "发布版本": version_for_pair,
        "result_id": result_id,
        "insight_id": result_id,
        "insight_version": insight_version,
        "洞察版本": insight_version,
        "project": project,
        "目标项目": project,
        "owner": owner_value,
        "洞察归属": owner_value,
        "shared_project": publication["shared_project"],
        "共享项目": publication["shared_project"],
        "auth_version": version,
        "授权版本": version,
        "authorized_fields": list(granted_fields),
        "授权字段": ",".join(granted_fields),
        "approved_fields": list(approved_fields),
        "sampling_fields": list(approved_fields),
        "获准采样字段清单": ",".join(approved_fields),
        "sampling_purpose": normalize_purpose(sampling_purpose),
        "采样用途": normalize_purpose(sampling_purpose),
        "published_at": publication["published_at"],
    }
    source_rows.append(source)

    return {
        "ok": True,
        "published": True,
        "publication": publication,
        "publication_id": publication_id,
        "publication_version": version_for_pair,
        "source": source,
        "source_id": source_id,
        "result_id": result_id,
        "mining_id": result_id,
        "insight_id": result_id,
        "insight_version": insight_version,
        "project": project,
        "target_project": project,
        "owner": owner_value,
        "insight_owner": owner_value,
        "shared_project": publication["shared_project"],
        "auth_version": version,
        "authorized_fields": list(granted_fields),
        "approved_fields": list(approved_fields),
        "sampling_fields": list(approved_fields),
        "获准采样字段清单": list(approved_fields),
        "sampling_purpose": normalize_purpose(sampling_purpose),
        "requested_fields": requested,
        "unauthorized_fields": unauthorized_fields,
        "unavailable_fields": unavailable_fields,
        "not_granted_fields": not_granted_fields,
        "message": (
            f"洞察 {result_id} 已发布给项目 {project}（授权版本 v{version}），"
            f"获准采样字段：{','.join(approved_fields) if approved_fields else '无'}"
        ),
    }


def find_publication(publication_id: int) -> dict[str, Any] | None:
    for row in store.rows(PUBLICATION_MODULE):
        if _int(row.get("id", row.get("publication_id", -1)), -1) == int(publication_id):
            return row
    return None


def publication_for_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not source:
        return None
    publication_id = source.get("publication_id", source.get("发布编号"))
    if publication_id is None:
        return None
    return find_publication(_int(publication_id, -1))


def list_publications(
    *,
    result_id: int | None = None,
    project: str | None = None,
    source_id: int | None = None,
) -> list[dict[str, Any]]:
    rows = list(store.rows(PUBLICATION_MODULE))
    if source_id is not None:
        source = store.find("feature_source", int(source_id))
        publication = publication_for_source(source)
        return [publication] if publication else []
    if result_id is not None:
        rows = [
            row for row in rows
            if _int(row.get("result_id", row.get("insight_id", -1)), -1) == int(result_id)
        ]
    if project is not None:
        rows = [
            row for row in rows
            if str(row.get("project", row.get("目标项目", ""))) == str(project)
        ]
    return rows


# ── 取样与分群 ──
def _field_sources(publication: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    provenance = {
        "module": "mining_result",
        "result_id": publication.get("result_id"),
        "insight_id": publication.get("insight_id", publication.get("result_id")),
        "insight_version": publication.get("insight_version"),
        "publication_id": publication.get("id", publication.get("publication_id")),
        "publication_version": publication.get("publication_version"),
        "auth_version": publication.get("auth_version"),
        "project": publication.get("project"),
    }
    return {field: dict(provenance) for field in fields}


def publication_samples(publication: dict[str, Any]) -> list[dict[str, Any]]:
    """读取该发布版本冻结的样本快照。

    发布后洞察可能继续演进；旧来源与旧归档必须留在原发布版本上，所以取样优先
    使用发布时冻结的样本，没有快照的历史记录才回退到洞察当前样本。
    """
    snapshot = publication.get("sample_snapshot")
    if isinstance(snapshot, list):
        return [dict(item) for item in snapshot if isinstance(item, dict)]
    return insight_samples(_int(publication.get("result_id"), -1))


def _sample_stats(
    samples: list[dict[str, Any]],
    fields: list[str],
) -> dict[str, Any]:
    rendered = [
        {field: _sample_value(sample, field) for field in fields}
        for sample in samples
    ]
    null_counts = {
        field: sum(1 for sample in samples if _is_null(_sample_value(sample, field)))
        for field in fields
    }
    total = len(samples)
    null_rate = {
        field: (count / total if total else 0.0)
        for field, count in null_counts.items()
    }
    per_field: dict[str, Any] = {}
    for field in fields:
        # 便于调用方按字段名直接取数：confidence_null_rate / cluster_label_null_count …
        per_field[f"{field}_null_rate"] = null_rate[field]
        per_field[f"{field}_null_count"] = null_counts[field]
    return {
        "samples": rendered,
        "reference_samples": rendered,
        "sample_count": total,
        "row_count": total,
        "reference_sample_count": total,
        "fields_used": list(fields),
        "used_fields": list(fields),
        "sampling_fields": list(fields),
        "null_counts": null_counts,
        "null_rate": null_rate,
        "null_ratio": null_rate,
        "空值率": null_rate,
        "field_null_rate": null_rate,
        **per_field,
    }


def sample_publication(publication_id: int, *, source_id: int | None = None) -> dict[str, Any]:
    """按发布时冻结的获准采样字段清单取参考样本并归档。

    未授权的字段既不会出现在样本里，也不会参与任何统计；分群相关指标只有在
    cluster_label 出现在该发布版本的获准清单里时才会生成。
    """
    publication = find_publication(publication_id)
    if publication is None:
        return {"ok": False, "message": f"发布记录 {publication_id} 不存在", "error": "publication_not_found"}

    fields = normalize_fields(
        publication.get("approved_fields", publication.get("sampling_fields"))
    )
    samples = publication_samples(publication)
    stats = _sample_stats(samples, fields)

    archive_rows = store.rows(ARCHIVE_MODULE)
    archive_id = _next_id(archive_rows)
    archive = {
        "id": archive_id,
        "archive_id": archive_id,
        "archived_at": _now(),
        "publication_id": publication.get("id", publication_id),
        "publication_version": publication.get("publication_version"),
        "source_id": source_id,
        "result_id": publication.get("result_id"),
        "insight_id": publication.get("insight_id", publication.get("result_id")),
        "insight_version": publication.get("insight_version"),
        "洞察版本": publication.get("insight_version"),
        "project": publication.get("project"),
        "目标项目": publication.get("project"),
        "owner": publication.get("owner"),
        "洞察归属": publication.get("owner"),
        "shared_project": publication.get("shared_project"),
        "共享项目": publication.get("shared_project"),
        "auth_version": publication.get("auth_version"),
        "授权版本": publication.get("auth_version"),
        "authorized_fields": list(normalize_fields(publication.get("authorized_fields"))),
        "approved_fields": list(fields),
        "sampling_fields": list(fields),
        "获准采样字段清单": list(fields),
        "fields_used": list(fields),
        "field_sources": _field_sources(publication, fields),
        "sample_count": stats["sample_count"],
        "null_rate": dict(stats["null_rate"]),
        "sampling_purpose": publication.get("sampling_purpose"),
        "采样用途": publication.get("sampling_purpose"),
        "status": "已归档",
    }
    # 只有该发布版本确实授权 cluster_label 时，归档中才出现分群统计。
    if CLUSTER_FIELD in fields:
        group_counts: dict[str, int] = {}
        for sample in samples:
            label = _sample_value(sample, CLUSTER_FIELD)
            key = "<空>" if _is_null(label) else str(label)
            group_counts[key] = group_counts.get(key, 0) + 1
        archive["grouped_by"] = CLUSTER_FIELD
        archive["group_counts"] = group_counts
        archive["cluster_stats"] = {"field": CLUSTER_FIELD, "counts": group_counts}
    archive_rows.append(archive)

    result = {
        "ok": True,
        "publication_id": publication.get("id", publication_id),
        "publication_version": publication.get("publication_version"),
        "source_id": source_id,
        "project": publication.get("project"),
        "target_project": publication.get("project"),
        "owner": publication.get("owner"),
        "insight_owner": publication.get("owner"),
        "shared_project": publication.get("shared_project"),
        "result_id": publication.get("result_id"),
        "mining_id": publication.get("result_id"),
        "insight_id": publication.get("insight_id", publication.get("result_id")),
        "insight_version": publication.get("insight_version"),
        "auth_version": publication.get("auth_version"),
        "authorized_fields": list(normalize_fields(publication.get("authorized_fields"))),
        "approved_fields": list(fields),
        "sampling_fields": list(fields),
        "获准采样字段清单": list(fields),
        "fields_used": list(fields),
        "field_sources": _field_sources(publication, fields),
        "sampling_purpose": publication.get("sampling_purpose"),
        "archive": archive,
        "archive_id": archive_id,
    }
    result.update(stats)
    result["message"] = (
        f"发布 {publication.get('id', publication_id)} 取样完成，"
        f"参考样本 {stats['sample_count']} 条，使用字段：{','.join(fields) if fields else '无'}"
    )
    return result


def cluster_publication(
    publication_id: int,
    field: str = CLUSTER_FIELD,
    *,
    source_id: int | None = None,
) -> dict[str, Any]:
    """按发布版本检查字段权限后再分群。

    未拿到 cluster_label 授权时直接拒绝，响应里不会出现 groups、sample_count
    等可能被误读成“按该列分组”的指标。
    """
    publication = find_publication(publication_id)
    if publication is None:
        return {"ok": False, "message": f"发布记录 {publication_id} 不存在", "error": "publication_not_found"}

    normalized = normalize_field(field)
    if field in CLUSTER_FIELD_ALIASES:
        normalized = CLUSTER_FIELD
    approved_fields = normalize_fields(
        publication.get("approved_fields", publication.get("sampling_fields"))
    )
    if normalized not in approved_fields:
        return {
            "ok": False,
            "allowed": False,
            "error": "field_not_authorized",
            "message": (
                f"字段 {normalized} 未在发布 {publication.get('id', publication_id)} "
                f"的授权版本 v{publication.get('auth_version')} 中授权，拒绝分群"
            ),
            "publication_id": publication.get("id", publication_id),
            "publication_version": publication.get("publication_version"),
            "source_id": source_id,
            "project": publication.get("project"),
            "result_id": publication.get("result_id"),
            "insight_id": publication.get("insight_id", publication.get("result_id")),
            "insight_version": publication.get("insight_version"),
            "auth_version": publication.get("auth_version"),
            "approved_fields": approved_fields,
            "field": normalized,
        }

    samples = publication_samples(publication)
    counts: dict[str, int] = {}
    for sample in samples:
        label = _sample_value(sample, normalized)
        key = "<空>" if _is_null(label) else str(label)
        counts[key] = counts.get(key, 0) + 1
    return {
        "ok": True,
        "allowed": True,
        "publication_id": publication.get("id", publication_id),
        "publication_version": publication.get("publication_version"),
        "source_id": source_id,
        "project": publication.get("project"),
        "result_id": publication.get("result_id"),
        "insight_id": publication.get("insight_id", publication.get("result_id")),
        "insight_version": publication.get("insight_version"),
        "auth_version": publication.get("auth_version"),
        "approved_fields": approved_fields,
        "field": normalized,
        "grouped_by": normalized,
        "groups": counts,
        "group_counts": counts,
        "cluster_counts": counts,
        "sample_count": len(samples),
        "message": f"已按授权字段 {normalized} 完成分群",
    }


def list_archives(
    *,
    publication_id: int | None = None,
    source_id: int | None = None,
    field: str | None = None,
    result_id: int | None = None,
) -> list[dict[str, Any]]:
    rows = list(store.rows(ARCHIVE_MODULE))
    if publication_id is not None:
        rows = [row for row in rows if _int(row.get("publication_id", -1), -1) == int(publication_id)]
    if source_id is not None:
        rows = [row for row in rows if _int(row.get("source_id", -1), -1) == int(source_id)]
    if result_id is not None:
        rows = [row for row in rows if _int(row.get("result_id", -1), -1) == int(result_id)]
    if field is not None:
        normalized = normalize_field(field)
        rows = [
            row for row in rows
            if normalized in normalize_fields(row.get("fields_used", row.get("approved_fields")))
        ]
    return rows


def find_archive(archive_id: int) -> dict[str, Any] | None:
    for row in store.rows(ARCHIVE_MODULE):
        if _int(row.get("id", row.get("archive_id", -1)), -1) == int(archive_id):
            return row
    return None


def trace_insight_version(
    *,
    archive_id: int | None = None,
    field: str | None = None,
    source_id: int | None = None,
    publication_id: int | None = None,
) -> dict[str, Any]:
    """按归档里的字段回查发布时使用的洞察版本。"""
    if archive_id is not None:
        archive = find_archive(archive_id)
        if archive is None:
            return {"ok": False, "message": f"归档 {archive_id} 不存在", "error": "archive_not_found"}
        return {
            "ok": True,
            "archive_id": archive.get("id", archive_id),
            "publication_id": archive.get("publication_id"),
            "result_id": archive.get("result_id"),
            "insight_id": archive.get("insight_id", archive.get("result_id")),
            "insight_version": archive.get("insight_version"),
            "auth_version": archive.get("auth_version"),
            "project": archive.get("project"),
            "fields_used": normalize_fields(archive.get("fields_used", archive.get("approved_fields"))),
            "archive": archive,
            "matches": [archive],
        }

    archives = list_archives(
        publication_id=publication_id, source_id=source_id, field=field,
    )
    matches = [
        {
            "archive_id": archive.get("id", archive.get("archive_id")),
            "publication_id": archive.get("publication_id"),
            "publication_version": archive.get("publication_version"),
            "result_id": archive.get("result_id"),
            "insight_id": archive.get("insight_id", archive.get("result_id")),
            "insight_version": archive.get("insight_version"),
            "auth_version": archive.get("auth_version"),
            "project": archive.get("project"),
            "source_id": archive.get("source_id"),
            "fields_used": normalize_fields(archive.get("fields_used", archive.get("approved_fields"))),
            "archive": archive,
        }
        for archive in archives
    ]
    if not matches:
        return {
            "ok": False,
            "message": (
                f"没有归档使用字段 {normalize_field(field)}" if field else "没有匹配的归档"
            ),
            "error": "archive_not_found",
            "matches": [],
        }
    first = matches[0]
    return {
        "ok": True,
        "field": normalize_field(field) if field else None,
        "result_id": first["result_id"],
        "insight_id": first["insight_id"],
        "insight_version": first["insight_version"],
        "publication_id": first["publication_id"],
        "archive_id": first["archive_id"],
        "auth_version": first["auth_version"],
        "matches": matches,
        "insight_versions": [match["insight_version"] for match in matches],
    }


# ── 演示场景 ──
def ensure_demo_samples(result_id: int = 1) -> list[dict[str, Any]]:
    """确保演示洞察有三条参考样本：两个 A 群、一个 B 群，其中一条 confidence 为空。"""
    existing = insight_samples(result_id)
    if existing:
        return existing
    register_insight_samples(result_id, [
        {"cluster_label": "A", "confidence": 0.92, "insight_score": 0.81},
        {"cluster_label": "A", "confidence": None, "insight_score": 0.64},
        {"cluster_label": "B", "confidence": 0.78, "insight_score": 0.72},
    ])
    return insight_samples(result_id)


def run_demo(project: str = "P", result_id: int = 1) -> dict[str, Any]:
    """跑通“先只授权 confidence，扩权后再分群，旧来源仍受原版本约束”的场景。"""
    ensure_demo_samples(result_id)
    update_project_authorization(
        project, ["confidence"], sampling_purpose="普通取样", shared_project=False,
    )
    first = publish(
        result_id,
        project,
        sampling_purpose="普通取样",
        shared_project=False,
    )
    if not first.get("ok"):
        return {"ok": False, "stage": "publish_v1", "result": first}
    old_source_id = first["source_id"]
    old_sample = sample_publication(first["publication_id"], source_id=old_source_id)
    old_cluster = cluster_publication(first["publication_id"], CLUSTER_FIELD, source_id=old_source_id)

    # 第二次发布前先扩权：分群用途新增 cluster_label，授权版本随之递增。
    update_project_authorization(
        project, ["confidence", CLUSTER_FIELD], sampling_purpose="分群",
    )
    second = publish(
        result_id,
        project,
        sampling_purpose="分群",
        shared_project=False,
    )
    if not second.get("ok"):
        return {"ok": False, "stage": "publish_v2", "result": second}
    new_cluster = cluster_publication(second["publication_id"], CLUSTER_FIELD)
    old_cluster_retry = cluster_publication(first["publication_id"], CLUSTER_FIELD,
                                            source_id=old_source_id)
    trace = trace_insight_version(archive_id=old_sample.get("archive_id"))
    old_archive = find_archive(old_sample.get("archive_id"))

    confidence_rate = old_sample.get("null_rate", {}).get("confidence")
    return {
        "ok": True,
        "result_id": result_id,
        "project": project,
        "first_publication": first,
        "old_source_id": old_source_id,
        "old_sample": old_sample,
        "old_cluster": old_cluster,
        "second_publication": second,
        "new_cluster": new_cluster,
        "old_cluster_retry": old_cluster_retry,
        "trace": trace,
        "old_archive": old_archive,
        "checks": {
            "old_sample_count": old_sample.get("sample_count"),
            "old_confidence_null_rate": confidence_rate,
            "old_cluster_rejected": old_cluster.get("ok") is False,
            "new_groups": new_cluster.get("groups"),
            "old_cluster_retry_rejected": old_cluster_retry.get("ok") is False,
            "old_archive_fields": normalize_fields(
                (old_archive or {}).get("fields_used")
            ),
            "old_archive_has_cluster_stats": bool(
                (old_archive or {}).get("cluster_stats")
            ),
            "traced_insight_version": trace.get("insight_version"),
        },
    }
