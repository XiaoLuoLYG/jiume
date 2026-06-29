"""Inject active twin context into chat requests."""

from __future__ import annotations

from typing import Any

from jiume.audit.logger import append_audit_event
from jiume.personal_distillation.engine import PersonalDistillationEngine
from jiume.skills.catalog import LUCKIN_ORDER_SKILL_ID, mounted_skill_cards
from jiume.twins.store import TwinStore


def _distilled_context_text(twin_id: str, *, query: str = "") -> str:
    try:
        return PersonalDistillationEngine().active_context_text(twin_id, query=query)
    except Exception:
        return ""


def _context_block(profile: dict[str, Any], *, query: str = "") -> str:
    permissions = profile.get("permissions") if isinstance(profile.get("permissions"), dict) else {}
    skills = permissions.get("allowedSkillIds") if isinstance(permissions, dict) else []
    skill_ids = [str(item) for item in skills] if isinstance(skills, list) else []
    skill_cards = mounted_skill_cards(skill_ids)
    if skill_cards:
        skill_text = "\n".join(
            (
                f"- {skill['displayName']} (id: {skill['id']}, category: {skill['category']}, "
                f"risk: {skill['risk']}): {skill['summary']} Why JiuMe: {skill['whyJiume']}"
            )
            for skill in skill_cards
        )
    else:
        skill_text = "- none"
    memories = profile.get("memories") if isinstance(profile.get("memories"), list) else []
    memory_items = [str(item).strip() for item in memories if str(item).strip()]
    memory_text = "\n".join(f"- {item}" for item in memory_items[:8]) if memory_items else "- none"
    twin_id = str(profile.get("id") or "").strip()
    distilled_text = _distilled_context_text(twin_id, query=query) if twin_id else ""
    distilled_block = f"{distilled_text}\n" if distilled_text else ""
    luckin_note = ""
    if LUCKIN_ORDER_SKILL_ID in skill_ids:
        luckin_note = (
            "Luckin official MCP exception: use only these Luckin official MCP tools when needed: "
            "queryShopList, searchProductForMcp, switchProduct, queryProductDetailInfo, "
            "previewOrder, createOrder, queryOrderDetailInfo, cancelOrder. If Luckin previewOrder is clear "
            "and within policy, opening the `weixin://wxpay/` payOrderUrl returned by Luckin createOrder is allowed. "
            "The user's WeChat Pay confirmation is the payment approval. "
            "Ask before createOrder only when store/item/price/coupon/address/token ambiguous. "
            "When the user cancels, payment fails, or an unpaid order should not remain open, "
            "use queryOrderDetailInfo / cancelOrder to check status or cancel. "
            "Do not use QR code payment as the default path.\n"
        )
    return (
        "[JiuMe Twin Context]\n"
        f"Name: {profile.get('displayName')}\n"
        f"Purpose: {profile.get('purpose')}\n"
        f"Tone: {profile.get('tone')}\n"
        f"Permission mode: {permissions.get('defaultMode')}\n"
        f"Long-term memories:\n{memory_text}\n"
        f"Mounted skills:\n{skill_text}\n"
        f"{distilled_block}"
        f"{luckin_note}"
        "When the user asks for work that matches a mounted skill, route the task through that skill, "
        "ask for missing materials, and summarize the active skill you chose. Do not claim an unmounted skill is active.\n"
        "Represent the user only within these permissions. Ask before external actions, irreversible changes, "
        "calendar changes, payment, or sending messages outside this chat.\n"
        "[/JiuMe Twin Context]\n\n"
    )


def enrich_gateway_message(message: Any) -> Any:
    """Return a message whose params carry twin context for AgentServer prompts.

    The existing Message dataclass is mutable in the gateway path, so this helper
    keeps compatibility by mutating only the params/metadata dictionaries.
    """
    params = dict(getattr(message, "params", None) or {})
    method = str((getattr(message, "metadata", None) or {}).get("method") or "")
    if method != "chat.send":
        return message
    twin_id = str(params.get("twin_id") or params.get("twinId") or "").strip()
    if not twin_id:
        return message
    try:
        profile = TwinStore().get_twin(twin_id)
    except Exception:
        return message
    content_key = "content" if "content" in params else "query"
    original = str(params.get(content_key) or "")
    block = _context_block(profile, query=original)
    if original and "[JiuMe Twin Context]" not in original:
        params[content_key] = block + original
    params["jiume_twin"] = {
        "id": profile["id"],
        "displayName": profile.get("displayName"),
        "permissionMode": profile.get("permissions", {}).get("defaultMode"),
        "allowedSkillIds": profile.get("permissions", {}).get("allowedSkillIds", []),
    }
    message.params = params
    metadata = dict(getattr(message, "metadata", None) or {})
    metadata["jiume_twin_id"] = profile["id"]
    message.metadata = metadata
    append_audit_event(profile["id"], "chat.sent", {"session_id": getattr(message, "session_id", None)})
    return message
