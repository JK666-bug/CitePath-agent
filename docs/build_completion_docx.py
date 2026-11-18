#!/usr/bin/env python3
"""Build CitePath completion report Word doc using Mermaid-rendered figures."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
MMD = ROOT / "_mmd"
FIG = ROOT / "_docx_figs"
OUT = ROOT / "CitePath-完成报告.docx"

FIGURES = [
    ("06-loop.png", "图 0  主学习闭环"),
    ("01-overview.png", "图 1  系统拓扑"),
    ("02-upload.png", "图 2  上传与向量化"),
    ("03-plan.png", "图 3  计划生成"),
    ("04-exam.png", "图 4  考试出题与判分"),
    ("05-qa.png", "图 5  多窗口问答"),
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


def render_mermaid(force: bool = False) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    puppeteer = ensure_chrome_config()
    env = os.environ.copy()
    env["PUPPETEER_CACHE_DIR"] = str(Path.home() / ".cache" / "puppeteer")
    for mmd in sorted(MMD.glob("0*.mmd")):
        out = FIG / f"{mmd.stem}.png"
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
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial Unicode MS")
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


def add_figure(doc, path: Path, caption: str, width=Inches(6.2)):
    # Tall diagrams get a slightly smaller width so they fit a page better.
    from PIL import Image

    with Image.open(path) as im:
        w, h = im.size
    if h > w * 1.2:
        width = Inches(4.8)
    elif w > h * 3:
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


def build():
    render_mermaid(force=False)

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("CitePath-agent 完成报告")
    set_run_font(r, size=22, bold=True, color=RGBColor(65, 53, 46))

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("已落地功能 · 实现方式 · 数据流")
    set_run_font(r, size=12, color=RGBColor(126, 113, 102))

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = meta.add_run("流程图由 Mermaid CLI 渲染 · 可复跑 docs/build_completion_docx.py")
    set_run_font(r, size=9, color=RGBColor(160, 140, 120))

    add_figure(doc, FIG / FIGURES[0][0], FIGURES[0][1])

    add_heading(doc, "1. 项目是什么", 1)
    add_para(
        doc,
        "CitePath 是一门课一个学习闭环的 Agent 应用：上传讲义 → 解析入库与向量化 → "
        "LLM 生成学习计划 → 阅读 / 练习 / 考试 / 笔记 / 多窗口问答 → 日历与报告。",
    )
    add_table(
        doc,
        ["层", "技术"],
        [
            ["前端", "React 19 + TypeScript + Vite，自研路由"],
            ["后端", "FastAPI + Uvicorn + Pydantic"],
            ["关系库", "MySQL 8.4（schema.sql + 运行时 ensure_*）"],
            ["向量库", "Milvus（dense + BM25 + RRF）+ FastEmbed MiniLM + rerank"],
            ["PDF 入", "Docling（表格/公式）+ PyMuPDF 清洗"],
            ["PDF 出", "PyMuPDF 渲染笔记 / cheatsheet"],
            ["LLM", "LangChain，OpenAI 兼容；LLM_PROVIDER=hku|deepseek"],
        ],
    )
    add_para(
        doc,
        "目录要点：frontend/ SPA；backend/main.py 全量 API；agent/ 业务智能；"
        "db/ 持久化；ingest/ 解析；vector/ 检索；backend/data/pdfs/ 原始 PDF。",
    )

    add_heading(doc, "2. 总览数据流", 1)
    add_figure(doc, FIG / FIGURES[1][0], FIGURES[1][1])
    add_para(doc, "用户会话：cookie citepath_session → users / login_sessions。")

    add_heading(doc, "3. 已完成模块", 1)

    add_heading(doc, "3.1 认证", 2)
    add_bullets(
        doc,
        [
            "前端：/login、/register",
            "后端：POST /api/register|login|logout，GET /api/me",
            "存储：密码哈希；会话 cookie 14 天",
            "数据流：表单 → auth API → users / login_sessions → Depends(current_user)",
        ],
    )

    add_heading(doc, "3.2 课程与讲义上传", 2)
    add_bullets(
        doc,
        [
            "前端：课程列表 / 新建编辑 / Course information",
            "后端：课程 CRUD；上传 / 下载 / 删除文档",
            "步骤：SHA-256 去重 → Docling 抽页 → documents + pages → 落盘 → FastEmbed → Milvus",
            "文档 kind：lecture（讲义）、exam_case（样卷）、case_answer（答案；answer_mode: none|in_case|file）",
        ],
    )
    add_figure(doc, FIG / FIGURES[2][0], FIGURES[2][1])

    add_heading(doc, "3.3 学习计划 Plan", 2)
    add_bullets(
        doc,
        [
            "前端：/courses/:id/plan — 日期窗口、备注、选文档；任务按钮 Open / Practice / Exam / Reports / Done",
            "后端：GET/POST .../plan，POST .../plan/tasks/{id}/complete",
            "做法：agent/plan 按讲义切 chapter/concept/page，assemble_plan 排进起止日期",
            "阅读：/courses/:id/read 内嵌原始 PDF，Done 标记完成",
        ],
    )
    add_figure(doc, FIG / FIGURES[3][0], FIGURES[3][1])

    add_heading(doc, "3.4 练习 Practice", 2)
    add_bullets(
        doc,
        [
            "前端：练习入口、答题页、章节报告",
            "后端：按章节 start / open / answer / reports（可带练习偏好）",
            "做法：按 concept 进度自适应出题（MCQ / short）；grading 判分；错题可 LLM 讲解",
            "存储：practice_sessions / questions / answers / concept_progress",
        ],
    )

    add_heading(doc, "3.5 考试 Exam + 样卷", 2)
    add_bullets(
        doc,
        [
            "样卷 UI：课程 tab cases — 上传样卷 / 可选答案",
            "考试 UI：Plan 上 Exam → /exams/:courseId/:examId；交卷报告页",
            "出题：每 concept 约 1 MCQ + 1 short；无样卷仅用讲义；有样卷作风格参考，答案可参与 short 判分",
            "存储：exams / exam_questions / exam_answers / exam_drafts",
        ],
    )
    add_figure(doc, FIG / FIGURES[4][0], FIGURES[4][1])

    add_heading(doc, "3.6 笔记 Notes / Cheatsheet", 2)
    add_bullets(
        doc,
        [
            "前端：tab notes — 选讲义、模式 notes|cheatsheet、纸张 a4/a5/letter",
            "后端：POST .../notes 直接返回 PDF 附件（不落库）",
            "做法：读可用页 → LLM JSON 大纲 → PyMuPDF 排版",
        ],
    )

    add_heading(doc, "3.7 问答 Q&A（多窗口）", 2)
    add_bullets(
        doc,
        [
            "前端：左侧 chat 列表（新建/删除）、右侧对话自动滚底、Enter 发送、PDF chip（空选=闲聊）",
            "后端：GET/POST .../questions，DELETE .../questions/tabs/{tab_id}",
            "做法：load_skill(qa) + 工具循环 search_notes / search_web / study_status",
            "徽章：chat→Noted（闲聊）；材料 / web / account / refused 另有标签",
        ],
    )
    add_figure(doc, FIG / FIGURES[5][0], FIGURES[5][1])

    add_heading(doc, "3.8 日历与报告", 2)
    add_bullets(
        doc,
        [
            "日历 /calendar：前端聚合各课 plan 任务日期（无独立 calendar API）",
            "练习报告：GET .../chapters/{id}/reports",
            "考试报告：exams.report_json + 报告页",
            "问答工具侧：study_status（概念/章节掌握、错题、复习）",
        ],
    )

    add_heading(doc, "4. 核心表一览", 1)
    add_table(
        doc,
        ["域", "表"],
        [
            ["账号", "users, login_sessions, courses"],
            ["材料", "documents, pages"],
            ["计划", "study_plans, plan_chapters, plan_concepts, plan_chapter_pages"],
            ["练习", "practice_sessions, practice_questions, practice_answers, concept_progress"],
            ["考试", "exams, exam_questions, exam_answers, exam_drafts"],
            ["问答", "qa_records（含 tab_id / tab_title）"],
        ],
    )
    add_para(doc, "Milvus collection：lecture_segments（document_id, page_number, text, dense + sparse）。")

    add_heading(doc, "5. Skills 与路由", 1)
    add_para(
        doc,
        "Skills 目前仅 backend/agent/skills/qa/SKILL.md；Plan / Practice / Exam / Notes 使用代码内 system prompt。",
    )
    add_table(
        doc,
        ["路由", "用途"],
        [
            ["/login, /register", "登录注册"],
            ["/courses, /new, /edit", "课程"],
            ["/courses/:id/{plan,info,qa,cases,notes}", "课程页签"],
            ["/courses/:id/read", "阅读"],
            ["/calendar", "日历"],
            ["/practice/...", "练习"],
            ["/exams/:c/:e (+ /report)", "考试"],
        ],
    )

    add_heading(doc, "6. 完成度结论", 1)
    add_para(
        doc,
        "主学习闭环已打通：认证 → 上传/解析/向量化 → 计划 → 阅读 → 练习 → 考试（样卷可选）→ "
        "笔记 → 多窗口问答 → 日历/报告。QA 有 skill 文件；日历为前端聚合；笔记 PDF 即时生成不入库。",
    )

    doc.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
