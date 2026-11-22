"""挖掘结果管理领域服务：分析结果、洞察发现与关键发现的管理。"""
from __future__ import annotations

from typing import Any

from app.services import insight_publication
from app.services.base import BaseModuleService
from app.store import store


class MiningResultService(BaseModuleService):
    MODULE = "mining_result"
    ENTITY = "挖掘结果"
    OPERATION_TERM = "存储"
    LIST_FIELDS = ["结果编号", "分析主题", "算法类型", "洞察摘要", "关键分群", "置信度", "结果文件", "结果版本"]
    REQUIRED_FIELDS = ["结果编号", "分析主题", "算法类型"]
    STATUS_ORDER = ["草稿", "审核中", "已采纳", "已搁置"]
    ACTION_RULES = {"提交审核": "审核中", "确认采纳": "已采纳", "标记搁置": "已搁置"}
    NEGATIVE_ACTIONS = []

    # ── 链路4: 预测 → 挖掘结果 ──
    # ── 洞察发布: 授权检查 → 发布版本 → 特征源取样/分群 ──
    def register_insight_samples(
        self,
        result_id: int | None = None,
        samples: list[dict[str, Any]] | None = None,
        *,
        insight_id: int | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """登记洞察的参考样本，供发布后的普通取样与分群使用。"""
        result_id = int(result_id if result_id is not None else (insight_id or 0))
        if store.find(self.MODULE, result_id) is None:
            return {"ok": False, "message": f"挖掘结果 {result_id} 不存在"}
        return insight_publication.register_insight_samples(result_id, samples or rows or [])

    def publish_insight(
        self,
        result_id: int | None = None,
        project: str | None = None,
        *,
        target_project: str | None = None,
        project_id: str | None = None,
        authorized_fields: Any = None,
        fields: Any = None,
        approved_fields: Any = None,
        sampling_purpose: str = "普通取样",
        purpose: str | None = None,
        owner: str | None = None,
        insight_owner: str | None = None,
        shared_project: bool = False,
        auth_version: int | None = None,
        source_name: str | None = None,
        insight_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """把洞察发布给目标项目：先按项目与采样用途校验字段权限，再冻结发布版本。"""
        result_id = result_id if result_id is not None else kwargs.get("result_id", insight_id)
        project = project or target_project or project_id or kwargs.get("target")
        requested = authorized_fields
        for candidate in (fields, approved_fields, kwargs.get("sampling_fields")):
            if requested is None:
                requested = candidate
        return insight_publication.publish(
            int(result_id or 0),
            str(project or ""),
            authorized_fields=requested,
            sampling_purpose=purpose or sampling_purpose,
            owner=owner if owner is not None else insight_owner,
            shared_project=shared_project,
            auth_version=auth_version,
            source_name=source_name,
        )

    def list_insight_publications(
        self,
        result_id: int | None = None,
        project: str | None = None,
        *,
        insight_id: int | None = None,
        target_project: str | None = None,
    ) -> dict[str, Any]:
        """列出洞察的发布版本，包含目标项目、洞察归属与授权版本。"""
        result_id = result_id if result_id is not None else insight_id
        rows = insight_publication.list_publications(
            result_id=result_id, project=project or target_project)
        return {"ok": True, "items": rows, "total": len(rows)}

    def sample_published_insight(
        self,
        publication_id: int | None = None,
        *,
        source_id: int | None = None,
    ) -> dict[str, Any]:
        """按发布版本的获准采样字段清单取样，并归档字段来源。"""
        return insight_publication.sample_publication(int(publication_id or 0), source_id=source_id)

    def cluster_published_insight(
        self,
        publication_id: int | None = None,
        field: str | None = None,
        *,
        source_id: int | None = None,
    ) -> dict[str, Any]:
        """分群前先判定该发布版本的字段权限。"""
        return insight_publication.cluster_publication(
            int(publication_id or 0), field or insight_publication.CLUSTER_FIELD, source_id=source_id)

    def list_sampling_archives(
        self,
        *,
        publication_id: int | None = None,
        source_id: int | None = None,
        field: str | None = None,
        result_id: int | None = None,
        insight_id: int | None = None,
    ) -> dict[str, Any]:
        """按发布/来源/字段查询历史采样归档。"""
        rows = insight_publication.list_archives(
            publication_id=publication_id, source_id=source_id,
            field=field, result_id=result_id if result_id is not None else insight_id,
        )
        return {"ok": True, "items": rows, "total": len(rows)}

    def trace_insight_version(
        self,
        *,
        archive_id: int | None = None,
        field: str | None = None,
        source_id: int | None = None,
        publication_id: int | None = None,
    ) -> dict[str, Any]:
        """按归档里的字段回查发布时使用的洞察版本。"""
        return insight_publication.trace_insight_version(
            archive_id=archive_id, field=field,
            source_id=source_id, publication_id=publication_id,
        )

    def update_project_authorization(
        self,
        project: str,
        fields: Any = None,
        *,
        authorized_fields: Any = None,
        approved_fields: Any = None,
        sampling_purpose: str = "普通取样",
        purpose: str | None = None,
        shared_project: bool = False,
        auth_version: int | None = None,
    ) -> dict[str, Any]:
        """调整目标项目的字段授权；字段变化时授权版本自动递增。"""
        if fields is None:
            fields = authorized_fields if authorized_fields is not None else approved_fields
        row = insight_publication.update_project_authorization(
            project, fields or [], sampling_purpose=purpose or sampling_purpose,
            shared_project=shared_project, auth_version=auth_version,
        )
        return {"ok": True, "authorization": row}

    def get_project_authorization(self, project: str) -> dict[str, Any]:
        """读取目标项目当前的字段授权。"""
        row = insight_publication.project_authorization(project)
        if row is None:
            return {"ok": False, "message": f"项目 {project} 尚无字段授权", "project": project}
        return {"ok": True, "authorization": row}

    def run_publication_demo(self, project: str = "P", result_id: int = 1) -> dict[str, Any]:
        """演示两次发布、扩权、旧来源受限与旧归档回查的完整场景。"""
        return insight_publication.run_demo(project=project, result_id=result_id)

    # 常用别名：外部调用方按“发布 / 取样 / 分群 / 授权”直觉命名也能命中。
    publish = publish_insight
    publish_to_project = publish_insight
    sample = sample_published_insight
    cluster = cluster_published_insight
    authorize_project = update_project_authorization
    archives = list_sampling_archives

    def export_insights_to_labels(self, result_id: int) -> dict[str, Any]:
        """将挖掘结果的关键发现导出到业务场景标注模块，形成可复用的场景规则。"""
        result = store.find(self.MODULE, result_id)
        if result is None:
            return {"ok": False}
        label_rows = store.rows("scenario_label")
        next_id = max((int(r.get("id", 0)) for r in label_rows), default=0) + 1
        result["status"] = "已采纳"
        result["pending"] = False
        label_rows.append({
            "id": next_id,
            "status": "草稿",
            "pending": True,
            "abnormal": False,
            "标注编号": f"LABEL-{next_id:04d}",
            "场景名称": f"挖掘场景_{result.get('分析主题', 'unknown')}",
            "关联特征": result.get("关键分群", ""),
            "业务规则": result.get("洞察摘要", ""),
            "标注时间": "2026-11-18",
            "标注人": "system_auto",
            "标注状态": "草稿",
            "场景版本": "v1.0.0",
        })
        return {"ok": True, "result_id": result_id, "label_id": next_id}

    def aggregate_cluster_insights(self, result_id: int) -> dict[str, Any]:
        """聚合挖掘结果中关键分群的洞察数据并关联到聚类分析配置。"""
        result = store.find(self.MODULE, result_id)
        if result is None:
            return {"ok": False}
        cluster_rows = store.rows("cluster_config")
        related_clusters = [
            r.get("id") for r in cluster_rows
            if result.get("关键分群", "") and any(g.strip() in str(r.get("特征集", ""))
            for g in result.get("关键分群", "").split(","))
        ]
        return {
            "ok": True,
            "result_id": result_id,
            "clusters": result.get("关键分群", "").split(","),
            "related_cluster_configs": related_clusters,
        }

    def convert_insight_to_feature_source(self, result_id: int) -> dict[str, Any]:
        """将采纳的挖掘洞察转换为新的特征数据源，丰富下游模型的特征输入。"""
        result = store.find(self.MODULE, result_id)
        if result is None:
            return {"ok": False}
        source_rows = store.rows("feature_source")
        next_id = max((int(r.get("id", 0)) for r in source_rows), default=0) + 1
        source_rows.append({
            "id": next_id,
            "status": "草稿",
            "pending": True,
            "abnormal": False,
            "源编号": f"SRC-R{result_id:04d}",
            "源名称": f"洞察衍生特征_{result.get('分析主题', '')}",
            "数据表名": f"insight_derived_{result_id}",
            "连接配置": "hive_metastore",
            "字段清单": "insight_score,cluster_label,confidence",
            "采样比例": "0.5",
            "缓存策略": "memory_1h",
            "源版本": "v1.0.0",
        })
        return {"ok": True, "source_id": next_id, "result_id": result_id}

    def deduplicate_mining_results(self, result_ids: list[int]) -> dict[str, Any]:
        """对挖掘结果集进行去重处理，识别相似洞察并合并重复发现。"""
        topics = {}
        duplicates = []
        for rid in result_ids:
            r = store.find(self.MODULE, rid)
            if r is None:
                continue
            topic = r.get("分析主题", "")
            if topic in topics:
                duplicates.append({"id": rid, "similar_to": topics[topic]})
                r["status"] = "已搁置"
            else:
                topics[topic] = rid
        return {"ok": True, "unique_count": len(topics), "duplicate_count": len(duplicates),
                "duplicates": duplicates}