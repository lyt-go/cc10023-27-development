"""洞察发布、字段授权与采样归档的回归测试。

覆盖需求里的完整演示场景：
1. 三条洞察样本，两条 A、一条 B，其中一条 confidence 为空；
2. 第一次只授权 confidence：可发布，普通取样 3 条、confidence 空值率 1/3；
3. 没有 cluster_label 授权时按它分群必须被拒绝，且返回里不出现分组指标；
4. 扩权后第二次发布可以按 cluster_label 分群，得到 A=2、B=1；
5. 扩权后旧来源再试分群仍然拒绝，旧归档仍只有 confidence 的字段统计；
6. 按旧归档里的 confidence 可以回查到发布时使用的洞察版本。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import service_for
from app.store import store


DEMO_RESULT_ID = 1
DEMO_PROJECT = "PROJ-A"
GROUP_COUNT_KEYS = ("groups", "group_counts", "cluster_counts", "grouped_by",
                    "sample_count", "row_count", "null_rate", "null_counts")


class InsightPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        mining = service_for("mining_result")
        self.mining = mining
        self.source = service_for("feature_source")
        # 每条用例独立项目名，避免共享内存仓库互相影响。
        self.project = f"{DEMO_PROJECT}-{self._testMethodName}"
        self.mining.register_insight_samples(DEMO_RESULT_ID, [
            {"cluster_label": "A", "confidence": 0.92, "insight_score": 0.81},
            {"cluster_label": "A", "confidence": None, "insight_score": 0.64},
            {"cluster_label": "B", "confidence": 0.78, "insight_score": 0.72},
        ])

    # ── 发布前授权检查 ──
    def test_confidence_only_publish_and_ordinary_sample(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")

        published = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样")
        self.assertTrue(published["ok"], published)
        self.assertEqual(published["approved_fields"], ["confidence"])
        self.assertEqual(published["获准采样字段清单"], ["confidence"])
        self.assertEqual(published["target_project"], self.project)
        self.assertTrue(published["auth_version"] >= 1)
        self.assertTrue(published["owner"])

        sampled = self.mining.sample_published_insight(
            published["publication_id"], source_id=published["source_id"])
        self.assertTrue(sampled["ok"], sampled)
        self.assertEqual(sampled["sample_count"], 3)
        self.assertEqual(sampled["fields_used"], ["confidence"])
        self.assertAlmostEqual(sampled["null_rate"]["confidence"], 1 / 3)
        self.assertEqual(sampled["null_counts"]["confidence"], 1)
        for sample in sampled["samples"]:
            self.assertEqual(set(sample), {"confidence"})

    def test_cluster_rejected_without_authorization(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")
        published = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样")

        rejected = self.mining.cluster_published_insight(
            published["publication_id"], "cluster_label",
            source_id=published["source_id"])
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"], "field_not_authorized")
        self.assertEqual(rejected["approved_fields"], ["confidence"])
        # 拒绝结果不能暗含按 cluster_label 分组的任何指标。
        for key in GROUP_COUNT_KEYS:
            self.assertNotIn(key, rejected, f"拒绝响应不应包含 {key}")

    def test_publish_requires_target_project(self) -> None:
        missing = self.mining.publish_insight(DEMO_RESULT_ID, "")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"], "project_required")

    def test_publish_rejects_unauthorized_requested_field(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")
        rejected = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project,
            authorized_fields=["cluster_label"], sampling_purpose="分群")
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"], "no_authorized_fields")
        self.assertIn("cluster_label", rejected["unauthorized_fields"])

    # ── 两次发布与扩权 ──
    def test_second_publish_clusters_and_old_source_stays_restricted(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")
        first = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样")
        old_source_id = first["source_id"]
        old_sample = self.source.sample_published_source(old_source_id)
        self.assertEqual(old_sample["sample_count"], 3)
        self.assertEqual(old_sample["fields_used"], ["confidence"])

        # 扩权：为分群用途新增 cluster_label，授权版本递增。
        self.mining.update_project_authorization(
            self.project, ["confidence", "cluster_label"], sampling_purpose="分群")
        second = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="分群")
        self.assertTrue(second["ok"])
        self.assertGreater(second["auth_version"], first["auth_version"])
        self.assertEqual(second["publication_version"], 2)
        self.assertEqual(second["approved_fields"], ["confidence", "cluster_label"])

        clustered = self.source.cluster_published_source(second["source_id"])
        self.assertTrue(clustered["ok"], clustered)
        self.assertEqual(clustered["groups"], {"A": 2, "B": 1})

        # 旧来源仍按第一次发布版本判定，扩权不影响它。
        retry = self.source.cluster_published_source(old_source_id)
        self.assertFalse(retry["ok"])
        self.assertEqual(retry["error"], "field_not_authorized")
        self.assertEqual(retry["approved_fields"], ["confidence"])

        # 再用旧来源取样，仍然只有 confidence。
        again = self.source.sample_published_source(old_source_id)
        self.assertEqual(again["fields_used"], ["confidence"])
        self.assertEqual(again["sample_count"], 3)
        self.assertAlmostEqual(again["null_rate"]["confidence"], 1 / 3)

        # 重新打开旧归档，字段统计仍然只有 confidence，且没有分群统计。
        archives = self.source.published_source_archive(old_source_id)
        self.assertEqual(archives["total"], 2)
        for archive in archives["items"]:
            self.assertEqual(archive["fields_used"], ["confidence"])
            self.assertNotIn("cluster_stats", archive)
            self.assertNotIn("group_counts", archive)
            self.assertNotIn("cluster_label", archive["field_sources"])

    def test_publication_records_shared_project_owner_and_auth_version(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样",
            shared_project=True)
        published = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样",
            owner="INSIGHT-OWNER", shared_project=True)
        self.assertTrue(published["ok"], published)
        record = published["publication"]
        self.assertTrue(record["shared_project"])
        self.assertEqual(record["owner"], "INSIGHT-OWNER")
        self.assertEqual(record["project"], self.project)
        self.assertEqual(record["auth_version"], published["auth_version"])
        self.assertEqual(record["insight_version"], published["insight_version"])

    def test_archive_records_provenance_and_traces_insight_version(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")
        published = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样")
        sampled = self.mining.sample_published_insight(
            published["publication_id"], source_id=published["source_id"])
        archive = sampled["archive"]

        self.assertEqual(archive["project"], self.project)
        self.assertEqual(archive["result_id"], DEMO_RESULT_ID)
        self.assertEqual(archive["auth_version"], published["auth_version"])
        self.assertEqual(archive["fields_used"], ["confidence"])
        source_info = archive["field_sources"]["confidence"]
        self.assertEqual(source_info["module"], "mining_result")
        self.assertEqual(source_info["result_id"], DEMO_RESULT_ID)
        self.assertEqual(source_info["insight_version"], published["insight_version"])

        # 按归档里的字段回查：命中发布时使用的洞察版本。
        by_field = self.mining.trace_insight_version(
            field="confidence", source_id=published["source_id"])
        self.assertTrue(by_field["ok"], by_field)
        self.assertEqual(by_field["result_id"], DEMO_RESULT_ID)
        self.assertEqual(by_field["insight_version"], published["insight_version"])
        self.assertEqual(by_field["publication_id"], published["publication_id"])

        by_archive = self.mining.trace_insight_version(archive_id=sampled["archive_id"])
        self.assertTrue(by_archive["ok"], by_archive)
        self.assertEqual(by_archive["insight_version"], published["insight_version"])

        # cluster_label 没有参与该归档的统计，按它回查不应命中旧归档。
        by_cluster = self.mining.trace_insight_version(
            field="cluster_label", source_id=published["source_id"])
        self.assertFalse(by_cluster["ok"])

    def test_archive_immunity_to_later_permission_changes(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")
        published = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样")
        sampled = self.mining.sample_published_insight(
            published["publication_id"], source_id=published["source_id"])
        archive_id = sampled["archive_id"]

        # 之后把项目扩权到 cluster_label，历史归档仍按原发布版本读取。
        self.mining.update_project_authorization(
            self.project, ["confidence", "cluster_label"], sampling_purpose="分群")
        historical = self.mining.trace_insight_version(archive_id=archive_id)
        self.assertEqual(historical["fields_used"], ["confidence"])
        self.assertEqual(historical["auth_version"], published["auth_version"])
        self.assertEqual(historical["archive"]["fields_used"], ["confidence"])

    # ── 演示入口 ──
    def test_old_publication_frozen_when_insight_evolves(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")
        published = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样")
        before = self.mining.sample_published_insight(
            published["publication_id"], source_id=published["source_id"])

        # 发布后洞察样本继续演进（A 群新增一条、B 群减到零条）。
        self.mining.register_insight_samples(DEMO_RESULT_ID, [
            {"cluster_label": "A", "confidence": 0.5},
            {"cluster_label": "A", "confidence": 0.6},
            {"cluster_label": "A", "confidence": None},
        ])
        after = self.mining.sample_published_insight(
            published["publication_id"], source_id=published["source_id"])
        self.assertEqual(after["sample_count"], before["sample_count"])
        self.assertEqual(after["samples"], before["samples"])
        self.assertAlmostEqual(after["null_rate"]["confidence"], 1 / 3)

    def test_old_publication_rejects_newly_granted_field_after_expansion(self) -> None:
        self.mining.update_project_authorization(
            self.project, ["confidence"], sampling_purpose="普通取样")
        first = self.mining.publish_insight(
            DEMO_RESULT_ID, self.project, sampling_purpose="普通取样")
        self.mining.update_project_authorization(
            self.project, ["confidence", "cluster_label"], sampling_purpose="分群")
        # 即使现在项目已经拥有 cluster_label，旧发布版本仍然拒绝。
        old = self.mining.cluster_published_insight(
            first["publication_id"], "cluster_label", source_id=first["source_id"])
        self.assertFalse(old["ok"])
        self.assertEqual(old["approved_fields"], ["confidence"])

    def test_demo_reports_expected_checks(self) -> None:
        demo = self.mining.run_publication_demo(project=f"DEMO-{self._testMethodName}")
        self.assertTrue(demo["ok"], demo)
        checks = demo["checks"]
        self.assertEqual(checks["old_sample_count"], 3)
        self.assertAlmostEqual(checks["old_confidence_null_rate"], 1 / 3)
        self.assertTrue(checks["old_cluster_rejected"])
        self.assertEqual(checks["new_groups"], {"A": 2, "B": 1})
        self.assertTrue(checks["old_cluster_retry_rejected"])
        self.assertEqual(checks["old_archive_fields"], ["confidence"])
        self.assertFalse(checks["old_archive_has_cluster_stats"])
        self.assertTrue(checks["traced_insight_version"])


if __name__ == "__main__":
    unittest.main()
