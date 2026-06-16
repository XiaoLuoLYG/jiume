from dataclasses import FrozenInstanceError

import pytest

from jiume.desktop.gateway_client import GatewayEvent
from jiume.desktop.one_line_companion import (
    DAILY_FORBIDDEN_LABELS,
    INFRASTRUCTURE_WORDS,
    ONE_LINE_INPUT_HINT,
    WORKING_STATUSES,
    CompanionAction,
    TaskCapsule,
    capsule_for_gateway_event,
    daily_label_is_allowed,
    done_capsule,
    failed_capsule,
    need_user_capsule,
    working_capsule,
)


def test_contract_keeps_composer_minimal_and_forbidden_daily_labels_are_not_allowed() -> None:
    assert ONE_LINE_INPUT_HINT == "想让我做什么？"
    assert daily_label_is_allowed("发送")
    for label in DAILY_FORBIDDEN_LABELS:
        assert not daily_label_is_allowed(label)
        assert not daily_label_is_allowed(f"请{label}")


def test_working_statuses_are_allowed_and_short() -> None:
    assert {"在想", "在看", "在整理", "等你确认", "快好了"} <= set(WORKING_STATUSES)
    for status in WORKING_STATUSES:
        capsule = working_capsule(status)
        assert capsule.mode == "working"
        assert capsule.short_status == status
        assert len(capsule.primary_text) <= 6

    assert working_capsule("连接 gateway").short_status == "在想"


def test_need_user_capsule_has_one_question_and_limited_actions() -> None:
    capsule = need_user_capsule("允许我继续整理这些文件，并在完成后给你一个摘要吗？")

    assert capsule.mode == "need_user"
    assert capsule.primary_text == capsule.question
    assert capsule.question.endswith("…")
    assert len(capsule.actions) <= 2
    assert [action.label for action in capsule.actions] == ["好的", "取消"]

    no_cancel = need_user_capsule("继续吗？", allow_cancel=False)
    assert [action.label for action in no_cancel.actions] == ["好的"]


def test_done_and_failed_capsules_keep_daily_copy_short_and_hide_infra_words() -> None:
    done = done_capsule(
        "已经整理好 gateway websocket request_id 里的长长长长长长长长长长长长长长长长长长长长长长内容。"
    )
    failed = failed_capsule("agentserver offline mode request_id exploded")

    assert done.mode == "done"
    assert done.summary == "整理好了。"
    assert len(done.summary) <= 28
    assert len(failed.summary) <= 28
    for word in INFRASTRUCTURE_WORDS:
        assert word.lower() not in done.summary.lower()
        assert word.lower() not in failed.summary.lower()
    assert failed.summary in {"这件事现在还不能继续。", "我卡住了，可以换个说法再试一次。"}


def test_done_capsule_hides_sensitive_final_content() -> None:
    raw = "/home/example/.ssh/id_rsa token=fake-secret-token private draft content"

    done = done_capsule(raw)
    with_artifact = done_capsule(raw, has_artifact=True)

    assert done.summary == "任务已结束。"
    assert with_artifact.summary == "整理好了。"
    assert [action.label for action in with_artifact.actions] == ["查看"]
    for visible in (done.summary, with_artifact.summary):
        assert ".ssh" not in visible
        assert "token" not in visible.lower()
        assert "private" not in visible.lower()


def test_task_capsule_is_immutable_and_actions_are_tuples() -> None:
    capsule = TaskCapsule(
        mode="done",
        summary="好了",
        actions=[CompanionAction(id="view", label="查看")],
    )

    assert isinstance(capsule.actions, tuple)
    assert capsule.actions == (CompanionAction(id="view", label="查看"),)
    with pytest.raises(FrozenInstanceError):
        capsule.summary = "改一下"  # type: ignore[misc]


def test_gateway_processing_status_maps_to_working_and_done_capsules() -> None:
    processing = GatewayEvent(
        kind="event",
        event="chat.processing_status",
        payload={"is_processing": True},
    )
    idle = GatewayEvent(
        kind="event",
        event="chat.processing_status",
        payload={"is_processing": False},
    )

    assert capsule_for_gateway_event(processing) == working_capsule("在整理")
    assert capsule_for_gateway_event(idle, current_reply="已经收好。") == done_capsule("已经收好。")


def test_gateway_ask_user_question_maps_to_one_question_and_two_actions() -> None:
    event = GatewayEvent(
        kind="event",
        event="chat.ask_user_question",
        payload={"questions": [{"question": "允许写入这份文件吗？"}]},
    )

    capsule = capsule_for_gateway_event(event)

    assert capsule is not None
    assert capsule.mode == "need_user"
    assert capsule.question == "允许写入这份文件吗？"
    assert [action.label for action in capsule.actions] == ["好的", "取消"]


def test_gateway_final_with_artifact_maps_to_done_with_view_action() -> None:
    event = GatewayEvent(
        kind="event",
        event="chat.final",
        payload={
            "content": "整理好了。",
            "artifacts": [{"name": "summary.md", "path": "/tmp/summary.md"}],
        },
    )

    capsule = capsule_for_gateway_event(event)

    assert capsule is not None
    assert capsule == done_capsule("整理好了。", has_artifact=True)
    assert [action.label for action in capsule.actions] == ["查看"]


def test_gateway_final_hides_sensitive_content_from_daily_capsule() -> None:
    event = GatewayEvent(
        kind="event",
        event="chat.final",
        payload={"content": "/home/example/secret.txt token=fake-secret-token"},
    )

    capsule = capsule_for_gateway_event(event)

    assert capsule == done_capsule("/home/example/secret.txt token=fake-secret-token")
    assert capsule is not None
    assert capsule.summary == "任务已结束。"
    assert "/home/example" not in capsule.primary_text
    assert "token" not in capsule.primary_text.lower()


def test_gateway_error_maps_to_infra_safe_failed_capsule() -> None:
    event = GatewayEvent(kind="event", event="chat.error", payload={"error": "gateway request_id failed"})

    capsule = capsule_for_gateway_event(event)

    assert capsule == failed_capsule("gateway request_id failed")
    assert capsule is not None
    assert capsule.mode == "done"
    for word in INFRASTRUCTURE_WORDS:
        assert word.lower() not in capsule.primary_text.lower()


def test_gateway_failed_subtask_update_maps_to_failed_capsule() -> None:
    event = GatewayEvent(
        kind="event",
        event="chat.subtask_update",
        payload={"description": "整理资料", "status": "failed"},
    )

    capsule = capsule_for_gateway_event(event)

    assert capsule == failed_capsule("整理资料 · failed")


def test_gateway_completed_subtask_update_stays_non_terminal_working() -> None:
    event = GatewayEvent(
        kind="event",
        event="chat.subtask_update",
        payload={"description": "整理资料", "status": "completed"},
    )

    capsule = capsule_for_gateway_event(event)

    assert capsule == working_capsule("快好了")
