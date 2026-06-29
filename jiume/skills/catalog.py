"""JiuMe's curated shelf of Swarm Skills.

The source list is intentionally small for the MVP: these are office, research,
creator, and engineering skills that fit a task-capable digital twin.
"""

from __future__ import annotations

from typing import Any

SWARM_SKILLS_SOURCE = "https://swarmskills.openjiuwen.com/"
SWARM_SKILLS_API = "https://swarmskills.openjiuwen.com/api/v1/skills"
SKILL_FILTER_ALL = "全部"
LUCKIN_ORDER_SKILL_ID = "jiume-luckin-order"

RECOMMENDED_SKILLS: list[dict[str, Any]] = [
    {
        "id": "dcc61b6172844691b5ebb1f11246fffe",
        "displayName": "会议纪要精炼团队",
        "category": "办公",
        "risk": "low",
        "summary": "从会议转写和杂乱笔记中提取决策、待办、争议点，输出可执行纪要。",
        "whyJiume": "最适合作为分身进入会议后的第一个真实任务。",
        "installsAllTime": 16,
        "stars": 0,
    },
    {
        "id": "c7dc8f03a5df49d78d2615f888495b11",
        "displayName": "数据分析团队",
        "category": "研究",
        "risk": "medium",
        "summary": "先做数据质量门禁，再从趋势、假设检验、因果视角并行分析。",
        "whyJiume": "适合让分身处理表格、实验数据和业务复盘。",
        "installsAllTime": 534,
        "stars": 1,
    },
    {
        "id": "f82ab797f71d40d0a11e7fb7720d8a3a",
        "displayName": "email-optimizer-team",
        "category": "办公",
        "risk": "medium",
        "summary": "优化高敏邮件的语气、清晰度和影响力，不用于随手闲聊。",
        "whyJiume": "适合让分身先起草、润色，再由本人确认发送。",
        "installsAllTime": 10,
        "stars": 0,
    },
    {
        "id": "365bc0ed273248258cba872862ffac5e",
        "displayName": "PRD评审委员会",
        "category": "产品",
        "risk": "low",
        "summary": "从工程可行性、用户价值、业务影响、批判质疑四个角度评审 PRD。",
        "whyJiume": "适合产品/创业场景中让分身做第一轮压力测试。",
        "installsAllTime": 162,
        "stars": 0,
    },
    {
        "id": "3a370e5b8f2844599c59ef593a9b9289",
        "displayName": "WiseDev 多角色产品交付团队",
        "category": "产品",
        "risk": "medium",
        "summary": "把模糊业务输入推进到需求、API、UX、前端原型和评审产物。",
        "whyJiume": "适合把分身定位成小型产品交付助理。",
        "installsAllTime": 69,
        "stars": 1,
    },
    {
        "id": "7719ed0ed15a41b5b98339aca610d2ce",
        "displayName": "doc-generator",
        "category": "文档",
        "risk": "low",
        "summary": "生成带图片的指导文档，当前多用于 JiuwenClaw 文档生成。",
        "whyJiume": "适合把任务结果沉淀成可读文档和交付说明。",
        "installsAllTime": 20,
        "stars": 0,
    },
    {
        "id": "533c94fbd04f4f6e974cc05c72fef156",
        "displayName": "screenshot",
        "category": "文档",
        "risk": "low",
        "summary": "提供截图能力，可与文档助手联合使用。",
        "whyJiume": "适合后续做桌面分身的可视化取证和报告插图。",
        "installsAllTime": 16,
        "stars": 0,
    },
    {
        "id": "76fcdde8c2ae4f3486fc37ed3bb2f8eb",
        "displayName": "社媒多平台团队",
        "category": "内容",
        "risk": "medium",
        "summary": "并行适配多平台内容，再做品牌一致性和合规复核。",
        "whyJiume": "适合让分身把一次想法扩散成多平台发布草稿。",
        "installsAllTime": 427,
        "stars": 1,
    },
    {
        "id": "2cc56bf1780a48448fe899a6a22321df",
        "displayName": "团队技能自动生成专家",
        "category": "技能",
        "risk": "medium",
        "summary": "创建、转换或修改多角色 Swarm Skills，不用于单 Agent skill。",
        "whyJiume": "直接对齐个人 skill 蒸馏和他人 skill 借用的产品方向。",
        "installsAllTime": 6669,
        "stars": 10,
    },
    {
        "id": "fec91784a26e4016918e2779c76457b0",
        "displayName": "代码评审专业组",
        "category": "研发",
        "risk": "low",
        "summary": "以乐观、悲观、架构三种视角并行评审 PR。",
        "whyJiume": "适合研发用户把分身变成常驻 reviewer。",
        "installsAllTime": 411,
        "stars": 0,
    },
    {
        "id": "a23995adce9b48d1a3aeaa7b0a7a212b",
        "displayName": "系统化调试团队",
        "category": "研发",
        "risk": "medium",
        "summary": "通过假设生成、证据收集、对抗分析定位非平凡 Bug。",
        "whyJiume": "适合让分身持续跟进复杂问题，而不是只给一次性建议。",
        "installsAllTime": 222,
        "stars": 1,
    },
    {
        "id": "3145d68a00654ff7a930660a16ff82c2",
        "displayName": "安全审计团队",
        "category": "研发",
        "risk": "high",
        "summary": "面向代码和系统变更的安全审计团队，适合合并前检查。",
        "whyJiume": "适合作为高风险动作前的守门 skill，需要审批提示。",
        "installsAllTime": 322,
        "stars": 0,
    },
    {
        "id": LUCKIN_ORDER_SKILL_ID,
        "displayName": "瑞幸下单支付助手",
        "category": "食",
        "risk": "high",
        "summary": "通过瑞幸官方 MCP 查询门店、选择商品、预览订单、创建订单，并打开返回的微信支付 deeplink。",
        "whyJiume": "适合演示 JiuMe 的食物佣人和支付守门能力；用户只在微信支付里最终确认一次。",
        "installsAllTime": 0,
        "stars": 0,
    },
]


def recommended_skills() -> list[dict[str, Any]]:
    """Return a detached copy so UI callers can safely annotate rows."""

    return [dict(item) for item in RECOMMENDED_SKILLS]


def skill_categories() -> list[str]:
    categories = sorted({str(skill.get("category") or "").strip() for skill in RECOMMENDED_SKILLS if skill.get("category")})
    if "个人" not in categories:
        categories.append("个人")
    return [SKILL_FILTER_ALL, *categories]


def skill_risks() -> list[str]:
    ordered = ["low", "medium", "high", "unknown"]
    present = {str(skill.get("risk") or "unknown").strip() for skill in RECOMMENDED_SKILLS}
    present.add("unknown")
    risks = [risk for risk in ordered if risk in present]
    risks.extend(sorted(present.difference(risks)))
    return [SKILL_FILTER_ALL, *risks]


def filter_recommended_skills(
    *,
    query: str = "",
    category: str = SKILL_FILTER_ALL,
    risk: str = SKILL_FILTER_ALL,
    enabled_skill_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    enabled = {str(item or "").strip() for item in enabled_skill_ids or [] if str(item or "").strip()}
    needle = " ".join(str(query or "").lower().split())
    category = str(category or SKILL_FILTER_ALL).strip() or SKILL_FILTER_ALL
    risk = str(risk or SKILL_FILTER_ALL).strip() or SKILL_FILTER_ALL
    matched: list[tuple[int, dict[str, Any]]] = []
    known_ids: set[str] = set()
    for index, skill in enumerate(RECOMMENDED_SKILLS):
        known_ids.add(str(skill["id"]))
        if category != SKILL_FILTER_ALL and str(skill.get("category") or "") != category:
            continue
        if risk != SKILL_FILTER_ALL and str(skill.get("risk") or "") != risk:
            continue
        haystack = " ".join(
            str(skill.get(key) or "")
            for key in ("id", "displayName", "category", "risk", "summary", "whyJiume")
        ).lower()
        if needle and needle not in haystack:
            continue
        row = dict(skill)
        row["isEnabled"] = str(skill["id"]) in enabled
        matched.append((index, row))
    for skill_id in sorted(enabled.difference(known_ids)):
        custom = {
            "id": skill_id,
            "displayName": skill_id,
            "category": "个人",
            "risk": "unknown",
            "summary": "本地导入并挂载到 JiuMe 的个人 skill。Agent 会在本地 skills 目录中解析它。",
            "whyJiume": "这是用户给当前分身安装的本地能力。",
            "installsAllTime": 0,
            "stars": 0,
            "isEnabled": True,
            "isLocal": True,
        }
        if category != SKILL_FILTER_ALL and custom["category"] != category:
            continue
        if risk != SKILL_FILTER_ALL and custom["risk"] != risk:
            continue
        haystack = " ".join(str(custom.get(key) or "") for key in ("id", "displayName", "category", "risk", "summary", "whyJiume")).lower()
        if needle and needle not in haystack:
            continue
        matched.append((len(RECOMMENDED_SKILLS), custom))

    matched.sort(key=lambda item: (not item[1]["isEnabled"], -int(item[1].get("installsAllTime") or 0), item[0]))
    return [item for _, item in matched]


def recommended_skill_by_id(skill_id: str) -> dict[str, Any] | None:
    needle = str(skill_id or "").strip()
    if not needle:
        return None
    for skill in RECOMMENDED_SKILLS:
        if skill["id"] == needle:
            return dict(skill)
    return None


def mounted_skill_cards(skill_ids: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_id in skill_ids:
        skill_id = str(raw_id or "").strip()
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        known = recommended_skill_by_id(skill_id)
        if known:
            cards.append(known)
            continue
        cards.append(
            {
                "id": skill_id,
                "displayName": skill_id,
                "category": "personal",
                "risk": "unknown",
                "summary": "User-mounted personal skill. Use only if the local Agent runtime can resolve it.",
                "whyJiume": "Mounted by the user's JiuMe twin.",
            }
        )
    return cards


def catalog_payload() -> dict[str, Any]:
    return {
        "source": SWARM_SKILLS_SOURCE,
        "api": SWARM_SKILLS_API,
        "skills": recommended_skills(),
    }
