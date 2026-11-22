#!/usr/bin/env python3
"""Build COMP7608B-style Chinese final project description DOCX to Desktop."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
MMD = ROOT / "_mmd"
FIG = ROOT / "_docx_figs"
DESKTOP = Path.home() / "Desktop"
OUT = DESKTOP / "CitePath-项目描述-中文版.docx"
OUT_REPO = ROOT / "CitePath-项目描述-中文版.docx"

FIGURES = [
    ("06-loop.png", "图 1  CitePath 主学习闭环"),
    ("01-overview.png", "图 2  系统架构拓扑"),
    ("02-upload.png", "图 3  上传、解析与向量化流程"),
    ("03-plan.png", "图 4  学习计划生成流程"),
    ("07-practice.png", "图 5  章节练习（Learn）自适应流程"),
    ("04-exam.png", "图 6  考试出题与判分流程"),
    ("08-retrieval.png", "图 7  混合检索与重排流水线"),
    ("09-qa-decision.png", "图 8  问答自主决策与联网状态流转"),
    ("05-qa.png", "图 9  多窗口问答数据流"),
]


def ensure_chrome_config() -> Path:
    cfg = MMD / "puppeteer.json"
    if cfg.exists():
        return cfg
    root = Path.home() / ".cache" / "puppeteer" / "chrome-headless-shell"
    matches = sorted(root.glob("*/chrome-headless-shell-mac-arm64/chrome-headless-shell"))
    if not matches:
        matches = sorted(root.glob("**/chrome-headless-shell"))
    if not matches:
        raise SystemExit("Install chrome-headless-shell for mermaid-cli first.")
    cfg.write_text(
        json.dumps(
            {
                "executablePath": str(matches[-1]),
                "args": ["--no-sandbox", "--disable-setuid-sandbox"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return cfg


def render_mermaid(force: bool = True) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    puppeteer = ensure_chrome_config()
    env = os.environ.copy()
    env["PUPPETEER_CACHE_DIR"] = str(Path.home() / ".cache" / "puppeteer")
    needed = {name for name, _ in FIGURES}
    for mmd in sorted(MMD.glob("0*.mmd")):
        out = FIG / f"{mmd.stem}.png"
        if out.name not in needed:
            continue
        if out.exists() and not force and out.stat().st_mtime >= mmd.stat().st_mtime:
            continue
        print(f"render {mmd.name}")
        subprocess.run(
            [
                "npx",
                "--yes",
                "@mermaid-js/mermaid-cli@11.4.2",
                "-i",
                str(mmd),
                "-o",
                str(out),
                "-c",
                str(MMD / "theme.json"),
                "-p",
                str(puppeteer),
                "-b",
                "#FAF7F2",
                "-s",
                "2",
                "--width",
                "1600",
            ],
            check=True,
            env=env,
            cwd=str(ROOT),
        )


def set_run_font(run, size=11, bold=False, color=None):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = "Arial"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")
    if color:
        run.font.color.rgb = color


def add_heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        set_run_font(
            run,
            size=16 if level == 1 else 13,
            bold=True,
            color=RGBColor(65, 53, 46),
        )
    return p


def add_para(doc, text, size=11):
    p = doc.add_paragraph()
    run = p.add_run(text)
    set_run_font(run, size=size, color=RGBColor(65, 53, 46))
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing = 1.35
    return p


def add_bullets(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        run = p.add_run(item)
        set_run_font(run, size=11, color=RGBColor(65, 53, 46))
        p.paragraph_format.space_after = Pt(4)


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        set_run_font(run, size=10, bold=True, color=RGBColor(65, 53, 46))
        shading = cell._element.get_or_add_tcPr()
        shd = shading.makeelement(
            qn("w:shd"),
            {qn("w:fill"): "F5ECE0", qn("w:val"): "clear"},
        )
        shading.append(shd)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = table.rows[r + 1].cells[c]
            cell.text = ""
            run = cell.paragraphs[0].add_run(val)
            set_run_font(run, size=10, color=RGBColor(65, 53, 46))
    doc.add_paragraph()


def add_figure(doc, path: Path, caption: str, width=Inches(6.1)):
    from PIL import Image

    with Image.open(path) as im:
        w, h = im.size
    if h > w * 1.15:
        width = Inches(4.6)
    elif w > h * 2.8:
        width = Inches(6.3)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(path), width=width)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run(caption)
    set_run_font(r, size=9, color=RGBColor(126, 113, 102))
    cap.paragraph_format.space_after = Pt(14)


def fig(name: str) -> Path:
    return FIG / name


def build():
    render_mermaid(force=True)

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("CitePath：有计划地学、有依据地练")
    set_run_font(r, size=20, bold=True, color=RGBColor(65, 53, 46))

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("COMP7608B 期末项目 · 中文项目描述（交付版）")
    set_run_font(r, size=12, color=RGBColor(126, 113, 102))

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = meta.add_run(
        "Group 41 · Jiang Kai / Shi Junying / Tao Yu / Peng Luhan\n"
        "依据：COMP7608B Final Project Student Guideline · 对照 Proposal 与当前可运行系统"
    )
    set_run_font(r, size=9, color=RGBColor(160, 140, 120))

    # ------------------------------------------------------------------
    add_heading(doc, "1. 用户与提案连续性", 1)
    add_heading(doc, "1.1 目标用户与核心需求", 2)
    add_para(
        doc,
        "目标用户是需要依据真实课程讲义复习备考的学生。材料类型多、页码散，学生很难自行排优先级；"
        "“看懂讲义”也不等于“会做题”。普通问答工具回答问题，却不主动发现薄弱点、也不据此改计划。",
    )
    add_bullets(
        doc,
        [
            "按讲义与个人时间/目标生成分阶段学习计划（章节、概念、页码、预估时长）",
            "阅读后做章节练习，得到判分、参考答、评分点与页码出处",
            "根据掌握情况自适应后续题目，并支持独立问答（检索讲义并引用页码）",
            "保持与课程术语/方法一致，降低脱离讲义的幻觉风险",
        ],
    )
    add_figure(doc, fig("06-loop.png"), "图 1  CitePath 主学习闭环")

    add_heading(doc, "1.2 计划交付 vs 当前交付 vs 未完成", 2)
    add_table(
        doc,
        ["维度", "提案计划", "当前已交付", "说明 / 变更"],
        [
            [
                "材料入库",
                "PDF 解析 + 页级入库 + 向量检索",
                "Docling+清洗 → MySQL pages + Milvus hybrid",
                "已增强：BM25、RRF、rerank、跨页 bridge",
            ],
            [
                "学习计划",
                "按目标/时间生成章节计划并可调整",
                "LLM 切章/概念/页 → 排期 → 日历聚合",
                "支持周末跳过等偏好；动态重排仍可深化",
            ],
            [
                "章节练习",
                "混合题型、最多两轮、按错题再练",
                "Learn：连续对 2 次掌握；已去掉 Review 回合",
                "主动收敛到更清晰的掌握判定，减少冗余回合",
            ],
            [
                "考试",
                "提案侧重练习闭环",
                "新增章节考试 + 可选样卷风格",
                "超出提案：MCQ+short、草稿、报告",
            ],
            [
                "独立问答",
                "检索讲义并引用；无依据则拒答",
                "Agent 工具调用 + 多窗口；可要约联网",
                "联网 follow-up 为 web-only，避免复述讲义",
            ],
            [
                "笔记",
                "未作为主目标",
                "Notes / Cheatsheet PDF 即时生成",
                "增值功能；PDF 不落库",
            ],
        ],
    )
    add_para(
        doc,
        "主目标未改：仍是“讲义驱动的学习 Agent”。实现上从“章节两轮练习控制器”演进为"
        "“Plan + Learn Practice + Exam + Notes + QA”完整应用，自主决策更多体现在出题选题、"
        "检索工具选择与联网状态机上。",
    )

    # ------------------------------------------------------------------
    add_heading(doc, "2. 设计与实现", 1)
    add_heading(doc, "2.1 系统架构与技术栈", 2)
    add_figure(doc, fig("01-overview.png"), "图 2  系统架构拓扑")
    add_table(
        doc,
        ["层", "技术选型", "职责"],
        [
            ["前端", "React 19 + TypeScript + Vite", "上传、计划、阅读、练习、考试、笔记、多窗口问答、日历"],
            ["后端", "FastAPI + Uvicorn + Pydantic", "鉴权、API、业务编排入口 main.py"],
            ["Agent", "LangChain create_agent + 自写状态分支", "QA 工具循环；Plan/Practice/Exam/Notes 线性 LLM 流水线"],
            ["关系库", "MySQL 8.4", "用户、课程、页、计划、练习/考试答卷、qa_records"],
            ["向量库", "Milvus dense+BM25+RRF + FastEmbed + rerank", "讲义片段检索与页级聚合"],
            ["PDF", "Docling 入 / PyMuPDF 出", "解析清洗；笔记排版导出"],
            ["模型", "OpenAI 兼容（HKU / DeepSeek）", "计划、出题、简答判分、讲解、问答"],
        ],
    )

    add_heading(doc, "2.2 工作流与自主决策", 2)
    add_para(
        doc,
        "系统不是单一大图 StateGraph，而是：Python 规则分流 + QA 的 LangChain Agent（function calling）"
        "+ 若干线性 LLM 流水线。有意义的自主决策包括：切哪些章/概念、下一题考哪个 concept、"
        "出 MCQ 还是简答、检索哪些页、是否要约联网、联网后是否只采网页、何时结束练习会话。",
    )
    add_bullets(
        doc,
        [
            "工具：search_notes（混合检索）、search_web、account_info、学习状态类工具",
            "状态：cookie 会话；练习 concept_progress / streak；问答 tab_id 多窗口；联网 follow-up 依赖上一答是否要约",
            "停止/澄清：讲义不足则询问是否联网；用户同意后 web-only；网页为空则短拒并允许重试；寒暄不搜讲义",
            "人确认：上传材料、选 PDF、开启 Web chip、同意联网、开始练习/考试均需用户动作",
        ],
    )

    add_heading(doc, "2.3 上传与知识库", 2)
    add_figure(doc, fig("02-upload.png"), "图 3  上传、解析与向量化流程")
    add_para(
        doc,
        "PDF 经 SHA-256 去重后解析入库：可用页写入 MySQL，原文落盘，片段写入 Milvus。"
        "切块约 110 token、重叠 20；跨页句子用 bridge_to 单向桥接。文档 kind 含 lecture / exam_case / case_answer。",
    )

    add_heading(doc, "2.4 计划、练习、考试、笔记", 2)
    add_figure(doc, fig("03-plan.png"), "图 4  学习计划生成流程")
    add_figure(doc, fig("07-practice.png"), "图 5  章节练习（Learn）自适应流程")
    add_bullets(
        doc,
        [
            "Plan：按讲义切 chapter/concept/page，排入日期窗口；阅读任务打开原 PDF；日历前端聚合任务",
            "Practice：按未掌握 concept 顺序；streak=0 出 MCQ，≥1 出简答；连续对 2 次掌握；全掌握后结束出报告（已删除 Review）",
            "简答判分：模型对照 3–5 条 rubric 计 hit；命中率 ≥ 80% 算对；错题可生成带页码讲解",
            "Exam：每 concept 约 1 MCQ + 1 short；可选样卷作风格参考；答案页可辅助 short 判分",
            "Notes：LLM 大纲 + PyMuPDF 渲染 notes/cheatsheet，直接下载，不落库",
        ],
    )
    add_figure(doc, fig("04-exam.png"), "图 6  考试出题与判分流程")

    add_heading(doc, "2.5 检索与问答", 2)
    add_figure(doc, fig("08-retrieval.png"), "图 7  混合检索与重排流水线")
    add_para(
        doc,
        "检索不做绝对相似度门槛，采用 top-k：dense COSINE + BM25 → RRF → cross-encoder rerank →"
        "聚合成最多约 4 页给模型。BM25 保证精确编号/术语能进候选；向量负责语义近邻。",
    )
    add_figure(doc, fig("09-qa-decision.png"), "图 8  问答自主决策与联网状态流转")
    add_figure(doc, fig("05-qa.png"), "图 9  多窗口问答数据流")

    add_heading(doc, "2.6 关键代码与配置锚点（task traces）", 2)
    add_table(
        doc,
        ["能力", "主要入口", "关键实现"],
        [
            ["上传入库", "POST /api/courses/{id}/documents", "ingest + vector/segments.sync_pages"],
            ["计划", "POST /api/courses/{id}/plan", "agent/plan.py"],
            ["练习", "chapters/{id}/practice + answer", "agent/practice.py + practice_select.py"],
            ["考试", "exams start/submit", "agent/exam.py + grading/score.py"],
            ["问答", "POST .../questions", "agent/qa.py + skills/qa/SKILL.md"],
            ["联网搜索", "search_web 工具", "agent/web.py（ddgs + 中英维基兜底）"],
            ["判分阈值", "PASS_MARK=0.8", "grading/score.py"],
        ],
    )

    # ------------------------------------------------------------------
    add_heading(doc, "3. 可靠性与恢复", 1)
    add_para(
        doc,
        "按指南要求，至少覆盖两类相关失败情境。以下为已实现的检测、有界恢复或安全停止策略。",
    )
    add_table(
        doc,
        ["失败情境", "如何检测", "恢复 / 停止", "用户反馈"],
        [
            [
                "讲义无法支撑回答",
                "检索页不足或模型判定不支撑",
                "不编造；要约联网；用户拒绝则停止",
                "说明缺口 + 是否联网的是非问",
            ],
            [
                "用户同意联网但网页为空",
                "search_pages 返回空",
                "web-only 短拒；不复述讲义、不灌通用知识",
                "提示换关键词再试",
            ],
            [
                "练习出题 JSON 不合法",
                "question_from_reply 校验失败",
                "同 prompt 重试一次；仍失败则报错结束",
                "提示稍后再试",
            ],
            [
                "会话中断 / 重复提交",
                "未答完题写入 MySQL；按 question_id 校验",
                "重开继续当前题；已答不计第二分",
                "回到同一道未完成题",
            ],
            [
                "重复外部动作（联网）",
                "每轮 web_done 门闩",
                "同轮不重复 search_web",
                "使用当轮已取网页",
            ],
        ],
    )
    add_para(
        doc,
        "风险：重复调用外部搜索可能带来延迟与不稳定结果；因此 QA 对 search_web 做单轮限制，"
        "并对“好的/可以”follow-up 固定为 web-only，避免把失败搜索伪装成讲义答案。",
    )

    # ------------------------------------------------------------------
    add_heading(doc, "4. 非功能需求", 1)
    add_table(
        doc,
        ["维度", "目标 / 可观察检查", "已采取措施", "权衡"],
        [
            [
                "延迟",
                "单次问答可完成；练习出题可感知等待",
                "检索 top-30 + 页上限；笔记即时生成不入库",
                "质量优先于极致低延迟",
            ],
            [
                "成本",
                "控制工具轮次与上下文长度",
                "MAX_TOOL_ROUNDS；页字符截断；web 结果条数限制",
                "少调用 vs 答案完整度",
            ],
            [
                "工作负载",
                "本机 Docker：MySQL + Milvus",
                "compose 部署；单课程多 PDF 串行上传处理",
                "实现简单，高峰并行有限",
            ],
            [
                "隐私",
                "凭据不入库提交物",
                "cookie 会话；.env 配密钥；提交需脱敏",
                "密钥由部署方自行配置",
            ],
            [
                "可引用性",
                "练习/问答尽量带页码",
                "强制 cited pages / sources 校验",
                "无依据则拒答或要约联网",
            ],
        ],
    )

    # ------------------------------------------------------------------
    add_heading(doc, "5. 评测", 1)
    add_heading(doc, "5.1 场景、基线与判定规则", 2)
    add_para(
        doc,
        "提案规划了 MIT 6.006 讲义划分、脚本会话与人工标注。当前仓库已落地的可复现检查以"
        "pytest 规则测试与端到端手工走查为主；LLM 判分场景保留明确 rubric 与人工抽查要求。",
    )
    add_table(
        doc,
        ["类别", "例子", "期望 / 判定"],
        [
            ["代表路径", "上传 → 计划 → 阅读 → 练习掌握 → 问答引用", "闭环可完成；答案带来源页"],
            ["挑战路径", "近义编号、跨页概念、讲义仅相关基础", "BM25/bridge 助召回；不足则澄清"],
            ["失败路径", "无关问题、空网页、非法出题 JSON", "拒答/要约/重试/短拒，不双计分"],
            ["规则基线", "无自适应的单轮批改", "对比：CitePath 按 streak/concept 选题并持久化进度"],
            ["程序判定", "MCQ 全对；简答 hit/total≥0.8", "grading/score.py + 单测"],
        ],
    )
    add_heading(doc, "5.2 结果、失败与局限", 2)
    add_bullets(
        doc,
        [
            "已验证：认证、多 PDF 上传、计划生成、练习掌握推进、考试、笔记导出、多窗口 QA、讲义引用与联网状态机",
            "已知失败：免费网页搜索偶发空结果（已加强维基/多后端）；模型偶发 supported 标记过严（已用引用回退）",
            "局限：未宣称提升真实学习效果；动态改计划仍可加强；LLM 出题/简答判分存在方差，需固定设置并人工抽查",
            "记录设置：模型经 LLM_PROVIDER；检索 CHUNK_TOKENS≈110、候选 30、返页约 4；PASS_MARK=0.8",
        ],
    )

    # ------------------------------------------------------------------
    add_heading(doc, "6. 贡献、归属与 AI 使用声明", 1)
    add_table(
        doc,
        ["成员", "主要贡献（请组内按实际微调）"],
        [
            ["Jiang Kai", "Agent/检索/问答与系统集成、报告与演示材料"],
            ["Shi Junying", "前端交互与学习闭环界面"],
            ["Tao Yu", "计划/练习/数据模型与评测用例"],
            ["Peng Luhan", "上传解析、考试/笔记与文档"],
        ],
    )
    add_para(
        doc,
        "复用与依赖：React、FastAPI、LangChain、Docling、PyMuPDF、FastEmbed、Milvus、MySQL、ddgs 等；"
        "评测材料可使用公开 MIT OCW 讲义。凭据不进入提交包，通过 .env 配置。",
    )
    add_para(
        doc,
        "AI 协助声明：报告撰写与部分实现讨论使用了 Cursor / 对话式编码助手；"
        "组内对正确性、可运行性与答辩解释负责。相关提示词可按课程要求另行附交；本文件为项目描述正文。",
    )

    add_heading(doc, "7. 运行入口（摘要）", 1)
    add_bullets(
        doc,
        [
            "依赖：Docker Desktop、Python 3.10+、Node.js；docker compose up -d 启动 MySQL/Milvus",
            "后端：backend/.venv + uvicorn main:app --host 127.0.0.1 --port 8000",
            "前端：frontend npm run dev -- --host 127.0.0.1 --port 5173",
            "配置：backend/.env 中的 API Key（HKU_API_KEY 等）；详见仓库 README",
        ],
    )

    add_heading(doc, "8. 小结", 1)
    add_para(
        doc,
        "CitePath 已交付可独立运行的完整 Agent 应用：面向可识别用户，在讲义约束下做计划、练习、考试与有出处问答，"
        "并在缺口处澄清、在失败时有界停止。自主性体现在工具选择、掌握度驱动出题与多轮联网状态，而非仅组件基准测试。",
    )

    DESKTOP.mkdir(parents=True, exist_ok=True)
    doc.save(OUT_REPO)
    shutil.copy2(OUT_REPO, OUT)
    print(f"Wrote {OUT}")
    print(f"Also kept {OUT_REPO}")


if __name__ == "__main__":
    build()
