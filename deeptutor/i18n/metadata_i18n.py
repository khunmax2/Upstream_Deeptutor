"""Localized display metadata for built-in tools and capabilities."""

from __future__ import annotations

_CAPABILITY_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "chat": {
        "en": "Default agentic chat with tools, retrieval, memory, and attachments.",
        "zh": "默认智能聊天，支持工具、检索、记忆和附件。",
        "th": "แชตอัจฉริยะเริ่มต้น รองรับเครื่องมือ การค้นคืน ความจำ และไฟล์แนบ",
    },
    "deep_solve": {
        "en": "Multi-step problem solving with planning, reasoning, and final writing.",
        "zh": "多步骤解题，包含规划、推理和最终作答。",
        "th": "การแก้โจทย์หลายขั้นตอน พร้อมการวางแผน การให้เหตุผล และการเขียนคำตอบสุดท้าย",
    },
    "deep_question": {
        "en": "Generate high-quality questions from templates, sources, or learning goals.",
        "zh": "基于模板、资料或学习目标生成高质量题目。",
        "th": "สร้างคำถามคุณภาพสูงจากเทมเพลต แหล่งข้อมูล หรือเป้าหมายการเรียนรู้",
    },
    "deep_research": {
        "en": "Iterative deep research that decomposes a topic and writes a report.",
        "zh": "迭代式深度研究，分解主题并生成研究报告。",
        "th": "การวิจัยเชิงลึกแบบวนซ้ำ ที่แยกย่อยหัวข้อและเขียนรายงาน",
    },
    "math_animator": {
        "en": "Generate math animations or storyboard images with Manim.",
        "zh": "使用 Manim 生成数学动画或分镜图。",
        "th": "สร้างแอนิเมชันคณิตศาสตร์หรือภาพสตอรีบอร์ดด้วย Manim",
    },
    "mastery_path": {
        "en": "Structured mastery-based learning with spaced repetition.",
        "zh": "结构化掌握式学习，结合间隔复习。",
        "th": "การเรียนแบบเน้นความเชี่ยวชาญอย่างเป็นระบบ พร้อมการทบทวนแบบเว้นช่วง",
    },
    "visualize": {
        "en": "Create visual explanations such as SVG, charts, Mermaid, HTML, or Manim.",
        "zh": "生成 SVG、图表、Mermaid、HTML 或 Manim 等可视化讲解。",
        "th": "สร้างคำอธิบายเชิงภาพ เช่น SVG, แผนภูมิ, Mermaid, HTML หรือ Manim",
    },
}

_TOOL_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "brainstorm": {
        "en": "Explore ideas broadly and organize them with rationale.",
        "zh": "广泛发散想法，并按理由组织结果。",
        "th": "ระดมความคิดอย่างกว้างขวางและจัดระเบียบพร้อมเหตุผล",
    },
    "code_execution": {
        "en": "Run sandboxed Python code for computation and data exploration.",
        "zh": "在沙箱中运行 Python，用于计算和数据探索。",
        "th": "รันโค้ด Python ในแซนด์บ็อกซ์เพื่อการคำนวณและสำรวจข้อมูล",
    },
    "exec": {
        "en": "Run shell commands inside an isolated sandbox workspace.",
        "zh": "在隔离沙箱工作区中运行 shell 命令。",
        "th": "รันคำสั่ง shell ในเวิร์กสเปซแซนด์บ็อกซ์ที่แยกออกมา",
    },
    "paper_search": {
        "en": "Search arXiv preprints and return paper metadata.",
        "zh": "搜索 arXiv 预印本并返回论文元数据。",
        "th": "ค้นหา preprint จาก arXiv และคืนข้อมูลเมตาของงานวิจัย",
    },
    "reason": {
        "en": "Use a dedicated reasoning model call for hard reasoning tasks.",
        "zh": "调用专门的推理模型处理高难度推理任务。",
        "th": "เรียกใช้โมเดลการให้เหตุผลเฉพาะทางสำหรับงานที่ต้องคิดหนัก",
    },
    "web_search": {
        "en": "Search the web and return sourced results.",
        "zh": "联网搜索并返回带来源的结果。",
        "th": "ค้นหาเว็บและคืนผลลัพธ์พร้อมแหล่งอ้างอิง",
    },
    "imagegen": {
        "en": "Generate images from a text prompt with the configured model.",
        "zh": "用已配置的模型，根据文字描述生成图片。",
        "th": "สร้างภาพจากคำสั่งข้อความด้วยโมเดลที่ตั้งค่าไว้",
    },
    "videogen": {
        "en": "Generate short videos from a text prompt with the configured model.",
        "zh": "用已配置的模型，根据文字描述生成短视频。",
        "th": "สร้างวิดีโอสั้นจากคำสั่งข้อความด้วยโมเดลที่ตั้งค่าไว้",
    },
}


def capability_description_i18n(name: str, fallback: str = "") -> dict[str, str]:
    values = _CAPABILITY_DESCRIPTIONS.get(name)
    if values:
        return dict(values)
    return {"en": fallback, "zh": fallback, "th": fallback}


def tool_description_i18n(name: str, fallback: str = "") -> dict[str, str]:
    values = _TOOL_DESCRIPTIONS.get(name)
    if values:
        return dict(values)
    return {"en": fallback, "zh": fallback, "th": fallback}


def localized_description(values: dict[str, str], language: str) -> str:
    # Imported lazily: this module is pulled in during early runtime bootstrap
    # (capability registry), before the prompt package is fully initialized.
    from deeptutor.services.prompt.language import normalize_agent_language

    lang = normalize_agent_language(language)
    return values.get(lang) or values.get("en") or values.get("zh") or ""


__all__ = [
    "capability_description_i18n",
    "localized_description",
    "tool_description_i18n",
]
