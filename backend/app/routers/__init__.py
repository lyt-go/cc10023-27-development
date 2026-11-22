"""业务路由汇总：洞察发布路由在前，通用资源路由在后。"""
from __future__ import annotations

from app.routers import insight, resource

# insight 里的固定路径段（publish / sample / cluster / archives）必须先注册，
# 否则会被 resource 的 /{module}/{entry_id} 动态路径抢先匹配。
ROUTERS = [insight, resource]
