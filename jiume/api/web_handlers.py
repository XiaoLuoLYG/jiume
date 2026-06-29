"""Register JiuMe WebSocket RPC handlers on JiuwenSwarm WebChannel."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from jiume.audit.logger import read_audit_events
from jiume.avatar.service import AvatarService
from jiume.personal_distillation.engine import PersonalDistillationEngine
from jiume.personal_distillation.models import DistillationJob
from jiume.twins.store import TwinStore

logger = logging.getLogger(__name__)


def _params(params: Any) -> dict[str, Any]:
    return dict(params) if isinstance(params, dict) else {}


def _twin_id(params: dict[str, Any], store: TwinStore) -> str:
    value = str(params.get("twin_id") or params.get("twinId") or "").strip()
    if value:
        return value
    active = store.get_active_twin_id()
    if not active:
        raise ValueError("twin_id is required")
    return active


def register_jiume_handlers(channel: Any) -> None:
    store = TwinStore()
    avatars = AvatarService(store)
    distill = PersonalDistillationEngine(store=store, twins_root=getattr(store, "root", None))

    async def _send(ws: Any, req_id: str, ok: bool, payload: dict[str, Any] | None = None,
                    error: str | None = None, code: str | None = None) -> None:
        await channel.send_response(ws, req_id, ok=ok, payload=payload or {}, error=error, code=code)

    def _wrap(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[..., Awaitable[None]]:
        async def _handler(ws: Any, req_id: str, params: Any, session_id: str) -> None:
            try:
                await _send(ws, req_id, True, fn(_params(params)))
            except FileNotFoundError as exc:
                await _send(ws, req_id, False, error=str(exc), code="NOT_FOUND")
            except ValueError as exc:
                await _send(ws, req_id, False, error=str(exc), code="BAD_REQUEST")
            except Exception as exc:  # noqa: BLE001
                logger.exception("[jiume] RPC failed: %s", exc)
                await _send(ws, req_id, False, error=str(exc), code="INTERNAL_ERROR")
        return _handler

    def _job(job: DistillationJob) -> dict[str, Any]:
        return job.to_dict()

    channel.register_method(
        "twin.list",
        _wrap(lambda p: {"twins": store.list_twins(), "activeTwinId": store.get_active_twin_id()}),
    )
    channel.register_method(
        "twin.create",
        _wrap(lambda p: {"twin": store.create_twin(p), "activeTwinId": store.get_active_twin_id()}),
    )
    channel.register_method("twin.get", _wrap(lambda p: {"twin": store.get_twin(_twin_id(p, store))}))
    channel.register_method("twin.update", _wrap(lambda p: {"twin": store.update_twin(_twin_id(p, store), p)}))
    channel.register_method("twin.delete", _wrap(lambda p: (store.delete_twin(_twin_id(p, store)) or {"ok": True})))
    channel.register_method("twin.set_active", _wrap(lambda p: {"twin": store.set_active_twin(_twin_id(p, store))}))

    channel.register_method(
        "twin.avatar.upload_source",
        _wrap(lambda p: {"upload": avatars.upload_source(_twin_id(p, store), p)}),
    )
    channel.register_method(
        "twin.avatar.generate",
        _wrap(lambda p: {"job": avatars.generate_avatar(_twin_id(p, store), str(p.get("provider") or "auto"))}),
    )
    channel.register_method(
        "twin.avatar.job_get",
        _wrap(lambda p: {"job": avatars.get_job(_twin_id(p, store), str(p.get("job_id") or p.get("jobId") or ""))}),
    )
    channel.register_method(
        "twin.avatar.get_manifest",
        _wrap(lambda p: {"manifest": avatars.get_manifest(_twin_id(p, store))}),
    )

    channel.register_method(
        "twin.skills.list",
        _wrap(lambda p: {"skills": store.get_twin(_twin_id(p, store)).get("permissions", {}).get("allowedSkillIds", [])}),
    )
    channel.register_method(
        "twin.skills.enable",
        _wrap(lambda p: {"twin": store.enable_skill(_twin_id(p, store), str(p.get("skill_id") or p.get("skillId") or ""))}),
    )
    channel.register_method(
        "twin.skills.disable",
        _wrap(lambda p: {"twin": store.disable_skill(_twin_id(p, store), str(p.get("skill_id") or p.get("skillId") or ""))}),
    )
    channel.register_method(
        "twin.skills.audit",
        _wrap(lambda p: {"events": read_audit_events(_twin_id(p, store), int(p.get("limit") or 100))}),
    )

    channel.register_method(
        "twin.distill.create",
        _wrap(lambda p: {"job": _job(distill.create_job(_twin_id(p, store), p))}),
    )
    channel.register_method(
        "twin.distill.list",
        _wrap(lambda p: {"jobs": [_job(job) for job in distill.list_jobs(_twin_id(p, store))]}),
    )
    channel.register_method(
        "twin.distill.get",
        _wrap(lambda p: {"job": _job(distill.get_job(_twin_id(p, store), str(p.get("job_id") or p.get("jobId") or "")))}),
    )
    channel.register_method(
        "twin.distill.test",
        _wrap(lambda p: {"job": _job(distill.test_job(_twin_id(p, store), str(p.get("job_id") or p.get("jobId") or "")))}),
    )
    channel.register_method(
        "twin.distill.install",
        _wrap(lambda p: {"job": _job(distill.install_job(_twin_id(p, store), str(p.get("job_id") or p.get("jobId") or "")))}),
    )
    channel.register_method(
        "twin.distill.reject",
        _wrap(
            lambda p: {
                "job": distill.reject_job(
                    _twin_id(p, store),
                    str(p.get("job_id") or p.get("jobId") or ""),
                    str(p.get("feedback") or ""),
                ).to_dict()
            }
        ),
    )
    channel.register_method(
        "twin.audit.list",
        _wrap(lambda p: {"events": read_audit_events(_twin_id(p, store), int(p.get("limit") or 100))}),
    )
