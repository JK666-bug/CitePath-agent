#!/usr/bin/env python3
"""Detailed COMP7608B Chinese final report (EN figures/tables) -> course report folder."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

REPORT_DIR = Path(
    "/Users/jiangkai/Documents/香港大学/课程/Large language model/report"
)
ASSETS = REPORT_DIR / "_report_assets"
OUT = REPORT_DIR / "CitePath-Final-Report-zhCN.docx"

FIGS = [
    ("06-loop.png", "Figure 1. End-to-end learning loop of CitePath."),
    ("01-overview.png", "Figure 2. System architecture (UI, API, agents, MySQL, Milvus)."),
    ("supplement-p1-img1.png", "Figure 3. Upload, parse and store workflow."),
    ("supplement-p2-img1.png", "Figure 4. Study-plan generation workflow."),
    ("supplement-p2-img2.png", "Figure 5. Bounded two-round chapter practice workflow."),
    ("supplement-p3-img1.png", "Figure 6. Exam generation and grading workflow."),
    ("supplement-p3-img2.png", "Figure 7. Course Q&A with hybrid retrieval and optional web search."),
]


def set_run_font(run, size=11, bold=False, color=None, east_asia="PingFang SC"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), east_asia)
    if color:
        run.font.color.rgb = color


def add_heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        set_run_font(
            run,
            size=16 if level == 1 else (13 if level == 2 else 11.5),
            bold=True,
            color=RGBColor(32, 32, 32),
        )
    return p


def add_para(doc, text, size=11, indent=True):
    p = doc.add_paragraph()
    run = p.add_run(text)
    set_run_font(run, size=size, color=RGBColor(32, 32, 32))
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    return p


def add_bullets(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        run = p.add_run(item)
        set_run_font(run, size=11, color=RGBColor(32, 32, 32))
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        set_run_font(run, size=9.5, bold=True, color=RGBColor(32, 32, 32))
        shading = cell._element.get_or_add_tcPr()
        shd = shading.makeelement(
            qn("w:shd"),
            {qn("w:fill"): "E8EEF5", qn("w:val"): "clear"},
        )
        shading.append(shd)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = table.rows[r + 1].cells[c]
            cell.text = ""
            run = cell.paragraphs[0].add_run(val)
            set_run_font(run, size=9, color=RGBColor(32, 32, 32))
    doc.add_paragraph()


def add_figure(doc, filename: str, caption: str):
    path = ASSETS / filename
    if not path.exists():
        add_para(doc, f"[Missing figure: {filename}]", indent=False)
        return
    from PIL import Image

    with Image.open(path) as im:
        w, h = im.size
    width = Inches(5.9)
    if h > w * 1.05:
        width = Inches(4.7)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=width)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run(caption)
    set_run_font(r, size=9, color=RGBColor(80, 80, 80))
    cap.paragraph_format.space_after = Pt(12)


def build():
    missing = [n for n, _ in FIGS if not (ASSETS / n).exists()]
    if missing:
        raise SystemExit(f"Missing assets: {missing}")

    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.2)
    sec.left_margin = Cm(2.3)
    sec.right_margin = Cm(2.3)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(t.add_run("COMP7608B Final Project Report"), size=18, bold=True)

    t2 = doc.add_paragraph()
    t2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(t2.add_run("CitePath：有计划地学、有依据地练"), size=16, bold=True)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(
        meta.add_run(
            "Group 41\n"
            "Jiang Kai (3036806840) · Shi Junying (3036838219)\n"
            "Tao Yu (3036792087) · Peng Luhan (3036791801)\n"
            "Code baseline: integrate/develop-20261118 @ a654932 (Version B)\n"
            "Course: COMP7608B Large Language Models"
        ),
        size=10,
        color=RGBColor(70, 70, 70),
    )

    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(
        note.add_run(
            "Report body in Chinese. Figure captions and table headers in English.\n"
            "Workflow diagrams reused from the project Supplement (Version B)."
        ),
        size=9,
        color=RGBColor(110, 110, 110),
    )

    # ==================================================================
    add_heading(doc, "1. 用户与提案连续性（Users and proposal continuity）", 1)

    add_heading(doc, "1.1 问题背景与目标用户", 2)
    add_para(
        doc,
        "大学课程材料通常以讲义 PDF、实验说明、作业要求等形式分散存在。尽管材料大体按授课顺序排列，"
        "它们并不会告诉学生“此刻该优先读哪几页”、如何在有限时间内协调阅读与练习，更不会根据真实作答表现"
        "动态指出薄弱概念。学生自我感觉“听懂了”与真正能独立作答之间往往存在落差；通用大模型问答虽然方便，"
        "却容易脱离本课程术语与讲法，也缺乏可核对的页码出处，从而增加误导风险。",
    )
    add_para(
        doc,
        "CitePath 的目标用户是需要依据真实课程讲义进行阶段性复习与备考的学生。系统假设用户可以提供课程 PDF、"
        "学习时间窗口与简要目标说明，并愿意在阅读后完成章节练习。系统的价值不在于替代阅读，而在于："
        "（1）把材料组织成可执行计划；（2）用有出处的练习暴露缺口；（3）在证据约束下回答问题并支持恢复与复现。",
    )

    add_heading(doc, "1.2 核心需求与范围", 2)
    add_para(doc, "结合提案与当前可运行系统，核心需求可概括为：")
    add_bullets(
        doc,
        [
            "材料驱动：以用户上传的课程 PDF 为主要证据；保留文档编号与原始页码，便于核对。",
            "计划生成：根据材料与时间窗口生成章节、概念、阅读页与任务日期；支持增量资料与版本历史。",
            "有界练习：选择题 + 简答题；会话内固定通过线（默认 80%）；最多两轮；第二轮聚焦薄弱概念。",
            "可恢复性：题组、草稿、成绩、解释状态持久化；中断后续答同一套题；重复提交不双计分。",
            "独立问答：优先检索本课讲义并引用页码；不足则澄清或要约联网；问答不改写练习成绩。",
            "可运行交付：非 notebook；Docker 启动 MySQL/Milvus；README/Runbook 可复现；密钥不入库。",
        ],
    )
    add_para(
        doc,
        "明确不在本项目承诺范围内的事项包括：证明真实学习成绩提升、大规模多租户生产运维、"
        "以及未完成人工双标注前的“正式教学质量指标已达标”声明。Fine-tuning / RLHF 不是本项目路径。",
    )
    add_figure(doc, "06-loop.png", FIGS[0][1])

    add_heading(doc, "1.3 提案计划、交付现状与变更说明", 2)
    add_para(
        doc,
        "提案目标是端到端原型：上传 → 计划 → 练习跟踪 → 反馈与调整 → 独立问答。"
        "当前 Version B（integrate/develop-20261118 @ a654932）已实现可独立运行的完整应用，"
        "并把早期“按概念连胜掌握 / 复习回合”演进为提案强调的“章节最多两轮”控制器；"
        "同时增强计划版本、资料归档恢复、解释重试、样卷/考试/笔记与评测工具链。"
        "主目标未改变，属于实现路径收敛与范围增强，不构成需走课程重大目标变更手续的方向替换。",
    )
    add_table(
        doc,
        ["Area", "Planned in proposal", "Delivered in Version B", "Gap / intentional change"],
        [
            [
                "Ingestion & retrieval",
                "Parse PDF; keep page IDs; vector search",
                "Docling page parse; MySQL pages; original PDF store; Milvus dense+BM25+RRF+rerank; cross-page bridge",
                "Stronger hybrid retrieval than the proposal sketch",
            ],
            [
                "Study plan",
                "Chapter sequence with concepts/pages/time",
                "LLM structuring + calendar layout + version history + incremental materials + conflict check",
                "Time estimates remain transparent heuristics",
            ],
            [
                "Chapter practice",
                "Mixed items; <=2 rounds; weak-concept follow-up; reports",
                "Atomic whole-round generation; configurable threshold; drafts; idempotent submit; retryable explanations; round reports",
                "Replaces earlier concept-streak / review-phase loop",
            ],
            [
                "Exam & notes",
                "Not the proposal core",
                "Chapter exams + optional exam-case style; notes/cheatsheet PDF export",
                "Added product scope for completeness",
            ],
            [
                "Independent Q&A",
                "Cited lecture answers; refuse if unsupported",
                "LangChain tool agent; multi-tab chats; optional web with offer/accept; study-status tools",
                "Public web quality depends on SERP availability",
            ],
            [
                "Formal evaluation",
                "Scripted sessions + human labels + baseline comparison",
                "Collectors, review window, smoke suites, preparation manifests; software acceptance evidence",
                "Official 120-run dual annotation still outstanding",
            ],
        ],
    )

    # ==================================================================
    add_heading(doc, "2. 设计与实现（Design and implementation）", 1)

    add_heading(doc, "2.1 总体架构与技术选型", 2)
    add_para(
        doc,
        "CitePath 采用前后端分离与“规则控制器 + LLM 生成器”的分工：程序负责状态机、通过线、轮次上限、"
        "幂等与权限；大模型负责计划文本、出题、简答点判、错题解释与问答综合。数据上，MySQL 保存结构化学习状态，"
        "Milvus 保存讲义片段向量；Docker Compose 中的 etcd/MinIO 是 Milvus standalone 的配套组件，"
        "不是业务 PDF 对象存储。业务原 PDF 目前保存在应用可访问的本地目录（课设演示足够；生产宜迁对象存储）。",
    )
    add_figure(doc, "01-overview.png", FIGS[1][1])
    add_table(
        doc,
        ["Layer", "Technology", "Responsibility"],
        [
            ["Frontend", "React 19 + TypeScript + Vite", "Auth UI, courses, plan/calendar, practice/exam, notes, multi-tab QA"],
            ["Backend API", "FastAPI + Uvicorn + Pydantic", "REST entry points, auth dependency, orchestration"],
            ["Agent layer", "LangChain create_agent + Python pipelines", "QA tool loop; plan/practice/exam/notes LLM chains"],
            ["Relational store", "MySQL 8.4", "Users, documents/pages, plans/versions, practice/exam, QA records"],
            ["Vector store", "Milvus + FastEmbed + cross-encoder rerank", "Hybrid lecture retrieval"],
            ["PDF pipeline", "Docling (parse) + PyMuPDF (page check / notes render)", "Ingest & export"],
            ["LLM providers", "HKU Azure-compatible or DeepSeek via LLM_PROVIDER", "Generation & short-answer grading"],
        ],
    )
    add_para(
        doc,
        "关键权衡：不把全部流程做成巨大 LangGraph 业务图，而是用可测试的 Python 状态转换保证“最多两轮、"
        "不双计分、未入库不出题”等硬约束；只在需要工具选择的问答场景使用 create_agent。"
        "这样既满足课程对自主决策与工具使用的要求，又降低答辩时难以解释的隐式跳转。",
    )

    add_heading(doc, "2.2 自主决策、观察响应与停止/澄清规则", 2)
    add_para(doc, "系统在下列节点做出有意义决策，并对观察结果作出响应：")
    add_bullets(
        doc,
        [
            "材料是否可用来出题：仅当 ingest_status=complete、资料 active、向量片段存在时，才允许生成新练习题。",
            "计划如何更新：增量纳入新页 vs 纯重排；用 expected_version 检测冲突，避免覆盖他人刚保存的计划。",
            "练习是否进入第二轮：根据本轮正式正确率与会话固定通过线判断；失败则只对薄弱概念出第二轮；第二轮后强制结束。",
            "问答调用哪些工具：寒暄不搜讲义；有 PDF 先 search_notes；不足则询问是否联网；用户确认后 web-only；Web chip 开启则可组合。",
            "解释是否需要：仅错题请求补救解释；正确题标记 not_required；解释失败保留可重试状态而非静默空白。",
        ],
    )
    add_para(
        doc,
        "停止与澄清示例：证据不足时不编造；联网无结果时短拒并允许换关键词；模型判分 JSON 非法时不伪造正式零分；"
        "旧 workflow_version 会话会被安全收尾，避免半套规则混跑。人确认保留在上传、选 PDF、开始练习/考试、同意联网等动作。",
    )

    add_heading(doc, "2.3 上传、解析与索引", 2)
    add_figure(doc, "supplement-p1-img1.png", FIGS[2][1])
    add_para(
        doc,
        "上传链路首先校验 PDF 并计算 SHA-256。若课程内已存在相同摘要，则复用文档记录，并在原文件缺失时尝试补回。"
        "新文件经 Docling 逐页抽取正文并清洗页眉页脚等噪声，同时用 PyMuPDF 校验页数。"
        "可用页写入 MySQL（保留原始页码），原 PDF 在向量写入前原子落盘；随后结构化切块（约 110 token、重叠约 20）、"
        "跨页 bridge_to、FastEmbed 向量化并写入 Milvus（dense COSINE + BM25 sparse，RRF 融合，再 cross-encoder rerank）。"
        "只有关系事务与向量 flush 成功后才标记 complete；失败写入 ingest_error，界面展示 Processing/Unavailable 与重传提示。"
        "归档删除保留原 ID 与历史引用，避免报告中的来源页变成“幽灵链接”。",
    )
    add_para(
        doc,
        "检索策略不做绝对相似度门槛，而采用 top-k：先取约 30 条混合候选，重排后聚合为有限页（问答约 4 页）送给模型。"
        "BM25 负责精确编号/术语进榜，向量负责语义近邻——这对应提案中“编号类事实容易被纯向量漏掉”的风险。",
    )

    add_heading(doc, "2.4 学习计划", 2)
    add_figure(doc, "supplement-p2-img1.png", FIGS[3][1])
    add_para(
        doc,
        "计划模块读取学生说明（目标、可选先修与每日可用时间等）与选定讲义页，调用 LLM 划分章节/概念/引用页，"
        "再由程序排入起止日期并生成 Reading/Practice/Exam 等任务入口。系统会给出阅读/练习时长的透明启发式估计，"
        "并在超预算时警告，而不是假装精确预测。重新规划时，已完成任务尽量保留；未完成任务可按薄弱章节优先调整日期；"
        "新讲义需显式选择后才增量分析新页。plan_versions 保存只读历史；写入携带 expected_version，冲突时要求用户重载。"
        "代码锚点：backend/agent/plan.py、planning_support.py、db/plans.py。",
    )

    add_heading(doc, "2.5 章节练习：两轮协议（核心控制器）", 2)
    add_figure(doc, "supplement-p2-img2.png", FIGS[4][1])
    add_para(
        doc,
        "练习是提案中最关键的自治工作流。会话创建时写入 workflow_version 与 passing_threshold（默认 0.8，会话内不可被恢复流程悄悄改掉）。"
        "第一轮对章节概念生成整套混合题（每概念通常含 MCQ 与 short），经格式校验后原子写入；学生逐题作答，可先 save_draft。"
        "MCQ 由程序精确比对选项字母；简答由模型对照 3–5 条来自讲义的 rubric 返回命中下标，命中比例达到 80% 算对。"
        "模型超时/非法 JSON/重复命中不会被“默认判错”成正式成绩，而是报错并保留已提交草稿，避免污染 round_results。"
        "一轮全部判分后才计算本轮正确率；达标则结束并出报告；未达标则仅针对本轮错题概念生成第二轮；第二轮无论是否通过都必须结束。"
        "报告区分 passed_round_1 / passed_round_2 / failed_after_2，并列出剩余薄弱概念与来源页，不把两轮分数简单平均。"
        "代码锚点：backend/agent/practice.py、grading/score.py、db/practice.py、agent/report_text.py。",
    )
    add_table(
        doc,
        ["Rule", "Implementation detail"],
        [
            ["MCQ", "choice_correct: exact option letter match"],
            ["Short answer", "LLM rubric hits; points_pass requires hits/total >= 0.8"],
            ["Round pass", "exam_pass(correct, total, session threshold); default 0.8"],
            ["Max rounds", "review_round in {1,2}; no third round generation"],
            ["Round-2 scope", "Only weak concepts from failed round-1 items"],
            ["Persistence", "store_round atomic; drafts; unique answer per question"],
            ["Explanations", "Wrong items only; status ready/failed/not_required; retry API"],
            ["Isolation", "Independent Q&A must not mutate practice scores"],
        ],
    )

    add_heading(doc, "2.6 考试与笔记", 2)
    add_figure(doc, "supplement-p3-img1.png", FIGS[5][1])
    add_para(
        doc,
        "考试按章节概念生成约各一题 MCQ 与简答，支持草稿与交卷报告；可选 exam_case 仅作为风格参考，"
        "答案页可在简答判分时作为附加依据，但不把样卷模式与“无样卷正式评测”混为一谈。"
        "笔记/cheatsheet：读取可用页 → LLM 产出结构化大纲 → PyMuPDF 渲染并直接返回 PDF 附件（不落库），"
        "用于复习导出而非长期内容管理。代码锚点：agent/exam.py、db/exams.py、agent/notes.py。",
    )

    add_heading(doc, "2.7 课程问答与工具调用", 2)
    add_figure(doc, "supplement-p3-img2.png", FIGS[6][1])
    add_para(
        doc,
        "问答使用 LangChain create_agent，系统提示来自 skills/qa/SKILL.md。工具包括 search_notes、search_web、"
        "account_info 以及练习/考试相关的只读学习状态工具。前端支持多窗口（tab_id/tab_title）与 PDF chip："
        "显式空选择表示闲聊；未传 document_ids 的旧请求默认可用全部可读讲义。"
        "当讲义相关但不足以自信作答时，系统先诚实说明并询问是否联网；用户回复“好的/可以/yes”等后进入 web-only 回合，"
        "不再复述已看过的讲义，也不用模型记忆冒充网页结果。Web chip 开启的普通回合则可在 search_notes 后强制 search_web 一次并融合。"
        "代码锚点：agent/qa.py、agent/web.py、vector/segments.py、vector/rerank.py。",
    )

    add_heading(doc, "2.8 模型、提示、数据状态与代码锚点汇总", 2)
    add_para(
        doc,
        "模型通过 agent/llm.py 统一封装：LLM_PROVIDER=hku|deepseek；HKU 默认部署 gpt-4.1-mini；"
        "DeepSeek 使用 OpenAI 兼容 Chat API（演示环境可配置 deepseek-chat / deepseek-flash）。"
        "telemetry 记录 operation、耗时、token 与可配置成本估算（缺单价则为 null，不把未知当成 0）。"
        "提示词分布：QA 有独立 SKILL.md；Plan/Practice/Exam/Notes/Grade 使用代码内 system prompt，"
        "并对 JSON 结构做程序校验与有限重试。",
    )
    add_table(
        doc,
        ["Capability", "Primary code anchors", "Persistent state"],
        [
            ["Auth/courses", "main.py; db/auth.py; db/courses.py", "users, login_sessions, courses"],
            ["Upload/index", "ingest/; db/uploads.py; vector/segments.py", "documents, pages, PDF files, Milvus segments"],
            ["Plan", "agent/plan.py; db/plans.py", "study_plans, plan_versions, plan_chapters/..."],
            ["Practice", "agent/practice.py; grading/score.py", "practice_sessions/questions/answers, round_results"],
            ["Exam", "agent/exam.py; db/exams.py", "exams, exam_questions/answers/drafts"],
            ["Notes", "agent/notes.py", "No DB row; PDF response stream"],
            ["Q&A", "agent/qa.py; skills/qa/SKILL.md", "qa_records (tab_id, cites, web_sources)"],
        ],
    )

    # ==================================================================
    add_heading(doc, "3. 可靠性与恢复（Reliability and recovery）", 1)
    add_para(
        doc,
        "课程要求至少测试两类相关失败。CitePath 把失败分成“证据失败、模型失败、存储/索引失败、并发/重复提交失败”。"
        "原则是：可恢复的尽量有界重试；不可恢复的安全停止并给用户可操作反馈；绝不通过编造或静默改分来“假装成功”。",
    )
    add_table(
        doc,
        ["Failure situation", "How detected", "Bounded recovery / safe stop", "User-visible feedback"],
        [
            [
                "Lecture evidence insufficient",
                "Empty/weak search_notes; model not confident",
                "No fabrication; offer web; stop if user declines",
                "Honest gap + yes/no web ask",
            ],
            [
                "Web accepted but empty/unusable",
                "search_pages returns []",
                "Web-only short refusal; no lecture rehash; optional retry",
                "Tell user no usable pages; suggest rephrase",
            ],
            [
                "Short-answer grader returns invalid JSON",
                "Parse/validate failure in _grade_shorts",
                "Do not invent official zero; keep draft; allow retry",
                "Error path; explanation/grading retry when applicable",
            ],
            [
                "Milvus index fails after parse",
                "Exception during sync_pages / flush",
                "Keep PDF+SQL pages; ingest_error; block new question gen",
                "Material unavailable / needs recovery",
            ],
            [
                "Practice interrupted mid-round",
                "Open session + unanswered question rows",
                "Resume same round question IDs; lock around submit",
                "Return to current item with draft if any",
            ],
            [
                "Duplicate submit after finish",
                "Unique answer + finished status",
                "Idempotent 200; scores unchanged",
                "Same finished report/rounds",
            ],
        ],
    )
    add_para(
        doc,
        "重复外部动作风险：公网搜索与 LLM 调用都有成本与不稳定性。QA 对 search_web 设置单轮门闩；"
        "LLM 客户端 max_retries=1；解释重试由 explanation_status/attempts 约束。"
        "真实联调中曾验证：已完成会话重复提交返回成功且两轮成绩不变；模型判分失败不会把整轮写成虚假正式分。",
    )

    # ==================================================================
    add_heading(doc, "4. 非功能需求（Non-functional requirements）", 1)
    add_para(
        doc,
        "非功能指标以“单人/小组演示可完成闭环”为操作假设，而不是互联网级 SLA。"
        "下表给出可观察检查、已采取措施、结果取向与权衡。",
    )
    add_table(
        doc,
        ["Dimension", "Target / observable check", "Implemented measures", "Result / trade-off"],
        [
            [
                "Latency",
                "Interactive demo; practice generation may take longer per round",
                "Context truncation; limited retrieved pages; telemetry timings",
                "Observed median model call ~2.7s in one live 16-question session; whole-round generation trades wait for consistency",
            ],
            [
                "Cost",
                "Bound tokens and tool calls",
                "Tool-round limits; usage log with tokens; optional price config",
                "Unknown unit price stays null (not fake zero); DeepSeek/HKU chosen by operator",
            ],
            [
                "Workload",
                "One Docker host for MySQL+Milvus",
                "compose stack; serial ingest",
                "Simple ops; limited multi-user parallelism",
            ],
            [
                "Privacy & access",
                "No secrets in ZIP; ownership on resources",
                ".env local keys; cookie auth; document ownership checks",
                "Deployer must supply keys; PDF currently on local disk for coursework",
            ],
            [
                "Citability",
                "Keep document_id + original page numbers",
                "Source validation in practice/exam/QA",
                "Prefer refuse/clarify over unsupported fluent answers",
            ],
            [
                "Memory footprint",
                "Comfortable ~16GB RAM for stack + Docling peaks",
                "Milvus standalone (+etcd/minio) + app process",
                "8GB possible but tight during parsing",
            ],
        ],
    )

    # ==================================================================
    add_heading(doc, "5. 评测（Evaluation）", 1)

    add_heading(doc, "5.1 评测分层：规则、联调、正式指标", 2)
    add_para(
        doc,
        "本项目把“测试通过”拆成三层，避免用单元测试数量冒充教学质量："
        "（1）程序规则与状态机正确性；（2）真实服务/浏览器联调；（3）需人工标签的正式指标"
        "（引用语义支持率、简答一致率、baseline/full 对比等）。第（3）层在提案中设定了目标阈值，"
        "目前已具备采集器、空白标注表与准备资产，但官方双人标注与 120 次对照尚未关闭，故不在此填写“已达成 85%”之类结论。",
    )

    add_heading(doc, "5.2 案例设计、判定规则与基线", 2)
    add_table(
        doc,
        ["Case type", "Example", "Reference outcome / judging rule"],
        [
            [
                "Representative",
                "Upload → plan → round-1 practice → report → cited QA",
                "Loop completes; citations when lecture-supported; no score mutation by QA",
            ],
            [
                "Challenging",
                "Near-twin codes; cross-page definitions; partial coverage of a topic",
                "Hybrid retrieval should surface exact tokens; otherwise clarify / offer web",
            ],
            [
                "Failure",
                "Unsupported question; empty web; incomplete ingest; grader timeout",
                "Refuse/recover/stop; no third round; no fabricated official score",
            ],
            [
                "Baseline contrast",
                "One-round grade + report only",
                "CitePath adds durable resume + bounded round-2 on weak concepts",
            ],
            [
                "Program metrics",
                "MCQ exact match; short rubric >=80%; round threshold",
                "Implemented & unit-tested in grading/score.py and practice controller",
            ],
        ],
    )
    add_para(
        doc,
        "简答 LLM 评判标准显式化为：逐条 rubric 是否被学生表述覆盖；只有命中列表合法才计分。"
        "课程要求“LLM judging 需明确标准 + 人工抽查”——因此正式发布前仍需人工核对一批简答命中，"
        "而不能只看模型自洽。",
    )

    add_heading(doc, "5.3 已观测结果（软件验收与真实联调）", 2)
    add_para(
        doc,
        "根据整合分支验收记录（2026-11-13 及后续 Version B 说明），在真实 Docker MySQL/Milvus 与配置密钥环境下，"
        "主要软件层结果如下（这些数字证明控制器与集成可用性，不自动等于教学质量）：",
    )
    add_table(
        doc,
        ["Check", "Observed result", "Meaning / limit"],
        [
            ["Backend regression", "284/284 passed", "Mocked externals; rule/state coverage"],
            ["Fixture UI smoke", "44/44 passed", "Front/back protocol compatibility"],
            ["Live browser read-only", "15/15 passed", "Real API; no mocked UI writes"],
            ["Live API probe", "Login/plan/docs/report/runtime identity OK", "Includes complete ingest & plan versions"],
            ["MySQL/Milvus probe", "Pages/segments present; sessions persisted", "e.g. lecture_segments loaded in probe env"],
            [
                "Live two-round practice",
                "16 items (8+8); scores 2/8 then 3/8; outcome failed_after_2; explanations ready for wrongs",
                "Shows controller+model path; not a quality benchmark claim",
            ],
            ["Duplicate submit", "HTTP 200; round scores unchanged", "Idempotence under finished session"],
            ["Model telemetry (sample session)", "27 OK calls; ~19.6k in / 2.8k out tokens; median ~2.7s", "Cost/latency observability"],
        ],
    )

    add_heading(doc, "5.4 失败、局限与复现设置", 2)
    add_bullets(
        doc,
        [
            "失败/不稳：公网搜索偶发空页；LLM 出题或简答命中存在方差；估时启发式需人工校准。",
            "局限：未证明提升考试分数；正式 120 次 baseline/full 与双人标注未完成；生产对象存储未接入。",
            "不允许的错误（即使总分好看也不接受）：出现第三轮练习、重复计分、问答改写练习成绩、把未知成本记为 0。",
            "复现设置：分支 integrate/develop-20261118 @ a654932；PASS_MARK=0.8；检索 top 候选约 30、返页约 4；CHUNK≈110；LLM_PROVIDER 与模型名写入 .env；证据索引见 docs/ACCEPTANCE-*.zh-CN.md、RUNBOOK.zh-CN.md、evaluation_assets/。",
        ],
    )
    add_table(
        doc,
        ["Evaluation asset", "Purpose"],
        [
            ["backend/tests/*", "Grading safety, rounds, plan conflicts, QA isolation"],
            ["frontend/tests/*", "UI/API smoke with fixtures"],
            ["tools/*smoke*.py / acceptance_*.py", "Storage/HTTP/live probes"],
            ["tools/review-window", "Human annotation UI"],
            ["evaluation_assets/ & evaluation CLI", "Formal collection preparation"],
            ["Supplement figures", "Version B workflow maps used in this report"],
        ],
    )

    # ==================================================================
    add_heading(doc, "6. 贡献与归属（Contributions and attribution）", 1)
    add_para(
        doc,
        "Group 41 按模块与验收角色协作。下表按交付贡献归纳；若最终提交名单或职责有微调，以仓库提交与答辩分工为准更新。",
    )
    add_table(
        doc,
        ["Member", "Primary contributions"],
        [
            [
                "Jiang Kai",
                "Docker/services, agent API, ingest/retrieval, Q&A tools, telemetry, system integration, final report drafting",
            ],
            [
                "Shi Junying",
                "Upload/plan/practice/QA UI flows, planning UX, report presentation, front-end integration checks",
            ],
            [
                "Tao Yu",
                "Grading rules, thresholds, two-round acceptance criteria, evaluation protocol & formal-prep assets",
            ],
            [
                "Peng Luhan",
                "Practice generation/grading/explanations/report text, recovery & draft behaviour, related hardening",
            ],
        ],
    )
    add_para(
        doc,
        "第三方与数据：React、FastAPI、LangChain/LangGraph、Docling、PyMuPDF、FastEmbed、Milvus、MySQL、ddgs 等；"
        "公开评测语料可使用 MIT OCW 6.006 讲义。Supplement PDF 中的英文流程图直接用于本报告 Figure 3–7。"
        "未完成披露：正式双人标注指标、生产对象存储、日历独立后端。无 mock 冒充主路径；评测夹具仅用于自动化检查。",
    )

    add_heading(doc, "7. AI 使用声明", 1)
    add_para(
        doc,
        "报告撰写、文字润色与部分实现讨论使用了 Cursor 等 AI 编程助手；组员对正确性、可运行性、"
        "评测边界表述与答辩解释负责。项目相关提示词可按课程要求另行附交；密钥与个人信息已从提交物中排除。"
        "若某次提示记录缺失，将在附交声明中注明。",
    )

    add_heading(doc, "8. 运行与提交信息摘要", 1)
    add_bullets(
        doc,
        [
            "入口：docker compose up -d；backend uvicorn main:app --host 127.0.0.1 --port 8000；frontend npm run dev -- --host 127.0.0.1 --port 5173。",
            "配置：backend/.env 中 LLM_PROVIDER 与对应 API key；勿提交 .env。",
            "文档：docs/RUNBOOK.zh-CN.md、UPSTREAM_INTEGRATION.md、ACCEPTANCE-2026-11-13.zh-CN.md。",
            "提交版本标识：GitHub branch integrate/develop-20261118，commit a654932。",
        ],
    )

    add_heading(doc, "9. 结论", 1)
    add_para(
        doc,
        "CitePath 已交付面向可识别学生用户的完整自治 Agent 应用：在讲义证据约束下进行计划、两轮练习、考试/笔记与有出处问答，"
        "能够根据观察结果进入补练或结束，并在证据不足、模型失败、索引失败与重复提交等情况下有界恢复或安全停止。"
        "系统满足 COMP7608B 对完整智能体（决策、工具、观察响应、停止/澄清）的要求；后续工作重点是关闭正式人工评测指标与运维硬化，"
        "而不是重新定义项目目标。",
    )

    doc.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
