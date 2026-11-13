# CitePath 18 步分工验收报告（2026-11-13）

本报告以 `CitePath_Steps_Color_Roles.pdf` 的 18 步分工表为验收基准，以 Group 41 项目提案为参考。验收对象是当前工作副本 `work\CitePath-agent`（从用户指出的代码目录复制，未改业务源码）。结论先行：

- **18 个步骤都有可运行的实现，没有发现需要改业务代码的功能缺口。**
- 本轮软件层验收全部通过：**284/284 后端回归、44/44 模拟浏览器检查、15/15 真实浏览器只读检查、真实 MySQL/Milvus 数据核对、1 次真实模型两轮练习（16 题）**。
- 本轮实际修复的是三类**交付差距**：文档技术描述与实现不一致、过期计数、验收脚本自身的提交字段错误。没有用文档或测试数量冒充模型质量或教学效果。
- **第 18 步只能完成到“可复现软件 + 空白标注表”**：正式 baseline/full 各 20 场景 × 3 次（共 120 次）、两位成员独立人工标注、引用语义支持率和真实价格成本仍需外部条件，不能由本报告代填。

## 角色与颜色

| 颜色 | 角色 | 成员 | 分工 |
| --- | --- | --- | --- |
| 🟦 | A | Tao Yu | 判分规则、通过线、两轮、验收标准、异常核查、正式评测 |
| 🟪 | B | Peng Luhan | 练习生成、批改、错题解释、报告文字、恢复 |
| 🟧 | C | Shi Junying | 上传/入库状态界面、学习计划、答题与报告界面、问答界面 |
| 🟩 | D | Jiang Kai | Docker 基础服务、Agent API、解析入库、检索、问答、日志 |

## 验收环境与边界

- 代码位置：`C:\Users\Administrator\Documents\Codex\2026-11-11\https-github-com-jk666-bug-citepath\work\CitePath-agent`；本轮在 `default-workspace\CitePath-agent` 的副本上运行，最后只同步文档、验收工具和证据，不改业务源码。
- 服务：Docker 中 `citepath-agent-mysql`、`citepath-agent-milvus`、`etcd`、`minio`、`attu` 均运行；API `127.0.0.1:8000`；前端 `127.0.0.1:5173`；模型提供方 `hku / gpt-4.1-mini`。
- 真实账户为专用集成账户 `citepath_it_live_...`，凭据只从本机私有文件读取，未写入报告、日志或交付目录。
- “284 项通过”是模拟外部依赖的回归结果；真实模型质量、引用语义和学生效果不由这些数字证明。

## 本轮实际运行结果

| 检查 | 结果 | 证据文件 |
| --- | --- | --- |
| 后端回归 | **284/284 通过**，6.392 秒 | `backend-tests-284.txt` |
| 前端类型检查 | `tsc -b` 通过（exit 0，无诊断） | `frontend-tsc.txt` |
| 前端生产构建 | 通过，约 0.7 秒 | `frontend-build.txt` |
| 前端 lint | **0 错误、13 警告**（12 项原有界面警告 + 1 项测试脚本 `catch (_)`） | `frontend-lint.txt` |
| 模拟 API 浏览器检查 | **44/44 通过**（practice 10、feedback 8、upstream 6、planning 12、restoration 8） | `ui-*-ui-smoke.txt` |
| 真实浏览器只读验收 | **15/15 通过**，真实 API，无 mock、无业务写操作 | `live-ui-acceptance.json`、`screenshots/*.png` |
| 真实 API 只读核对 | **10/10 通过**：登录、/me、课程、计划 7 章、2 份资料均 complete、3 个计划版本、报告 2 轮 16 题、问答历史、运行身份 hku | `api-probe.json` |
| 真实 MySQL 核对 | 7 份资料全部 `complete` 且 active；37 页；5 个练习会话（2 个 finished 均为 `failed_after_2`）；44 题、36 份作答；计划版本最多 4 | `mysql-probe.json` |
| 真实 Milvus 核对 | `lecture_segments` 已加载，**230 条片段**；384 维 dense + BM25 sparse；文档 6 有 30 条片段 | `milvus-probe.json` |
| 真实模型两轮练习 | 会话 5：8+8 题，第一轮 2/8、第二轮 3/8，`failed_after_2`，4 个剩余薄弱概念、2 个来源页；11 个错题解释 ready、5 个正确题 not_required、0 failed | `live-practice-acceptance.json`、`session-5-probe.json` |
| 重复提交 | 已完成会话再次提交返回 **200**，状态仍为 finished，两轮成绩不变 | `duplicate-probe.json` |
| 模型调用与操作日志 | 会话 5 共 **27 次模型调用全部 ok**，输入 19,577 / 输出 2,788 token，中位耗时 2,678 ms；44 条操作记录（16 次判分、17 次提交、11 次解释） | `session-5-probe.json` |
| 前一轮真实模型开发联调 | 64/64 通过（同一代码副本的历史运行，本轮未改业务源码） | `prior-live-integration-v8.json` |

## 18 步逐项验收

图例：✅ 本轮已验证；⏳ 软件已实现但正式结论依赖外部人工条件。

| 步骤 | 负责角色 | 要求（分工表） | 实现与证据 | 结论 |
| --- | --- | --- | --- | --- |
| 1 统一规则与接口 | 🟦 A；🟪🟧🟩 确认 | 判分规则、通过线、最多两轮、验收标准；确认各自模块接口 | `grading/score.py`：严格选项匹配、`points_pass` 5×命中≥4×总数（≥80%）、未四舍五入的章节通过判定；`test_grading_safety.py`、`test_practice_rounds.py`；接口说明 `frontend/BACKEND_INTEGRATION.zh-CN.md` | ✅ |
| 2 启动基础服务 | 🟩 D | Docker 启动 MySQL、Milvus，建表并持久化 | `docker-compose.yml`（MySQL 8.4 + named volume；Milvus/etcd/MinIO/Attu 都有持久化目录）；5 个容器实跑；MySQL 表计数与 Milvus 集合均实测；`db/schema.sql` | ✅ |
| 3 封装部署 Agent API | 🟩 D；🟪🟧 模块 | 统一模型接入、请求响应、超时、错误格式，接通各模块 | `main.py` FastAPI 605 行、`agent/llm.py`（HKU 60s / DeepSeek 120s、`max_retries=1`）；真实 API 健康、登录、运行身份 hku | ✅ |
| 4 上传课程资料 | 🟩 D；🟧 C | 保存 PDF 和学生原始说明，提供上传接口；上传页与状态 | `add_document` → `save_document`；原 PDF 在向量索引前原子保存（`db/document_files.py`）；`CourseInfo.tsx` 显示文件名、页数、可用页、Ready/Processing/Unavailable、失败原因与重传提示；真实 UI 资料与原始 PDF 链接检查通过 | ✅ |
| 5 解析并入库 | 🟩 D | 逐页解析，保留章节、原始页码、正文；分块写数据库与向量库 | `ingest/pdf_reader.py` 使用 Docling 逐页导出，PyMuPDF 只校验页数；跨页文本回填；`vector/segments.py` 结构化分块 + 跨页 bridge；MySQL 37 页、Milvus 230 条片段 | ✅ |
| 6 检查入库状态 | 🟩 D；🟧 C | 两类库都成功才可出题；失败说明原因；状态界面与可执行操作 | `_index_document` 先 `pending`，关系数据提交并向量 flush 后才 `complete`；`require_ingested_documents` 在新题生成前校验 status、active、`has_segments`；`CourseInfo` 展示错误与重传；`test_ingestion_status.py` 196 行 | ✅ |
| 7 生成学习计划 | 🟧 C | 章节顺序、概念、阅读页码、预计时间、练习入口；必要时补充信息 | `agent/plan.py` + `planning_support.py`：目标/先修/每日分钟、估时依据、容量与超预算、增量资料、版本冲突；真实计划 7 章、3 个只读版本；真实 UI 估时与移动端布局通过 | ✅ |
| 8 阅读与生成第一轮练习 | 🟪 B；🟦 A 核对；🟧 C 界面 | 检索讲义生成题目、标准答案、得分点、来源页；保存题组与作答 | `agent/practice.start_practice` → `_generate_round`；`question_from_reply` 严格校验概念、题型、4 个选项、3–5 个得分点、来源必须是本章页；`store_round` 原子保存整轮；真实会话 5 生成 8 题 | ✅ |
| 9 提交与批改 | 🟪 B；🟦 A；🟧 C | 保存答案；模型判简答命中得分点；选择题匹配、≥80%、章节正确率 | `answer_practice` 先存草稿，再 `_grade_shorts` 逐点判定；非法/缺失/重复结果报错不判错；`round_result` 独立算每轮；真实 16 题判分、轮次 2/8 与 3/8 | ✅ |
| 10 错题反馈与复习 | 🟪 B；🟦 A 核对；🟧 C 界面 | 只为错题生成带来源页码的解释，记录薄弱概念 | `_attempt_practice_explanation` 仅错题调用；`feedback_fields` 正确题 `not_required`；解释失败保存可重试状态；真实 11 个错题解释 ready、5 个正确题 not_required、0 failed；报告带来源 | ✅ |
| 11 判断通过或补练 | 🟦 A；🟪 B | 通过线函数、默认 80%、会话内固定；未通过只对薄弱概念生成第二轮 | `validate_threshold`/`exam_pass`；`create_session` 保存 threshold，恢复不改；会话 5 阈值 0.8；`_generate_round` 第二轮只取本轮错题概念；`test_resume_keeps_saved_question_ids_and_threshold` | ✅ |
| 12 第二轮结束与报告 | 🟦 A；🟪 B；🟧 C | 两轮成绩、通过状态、剩余薄弱点与来源；第二轮结束不生成第三轮；补充报告文字 | `_ensure_question` 在 round 2 结束或通过时发布报告；`store_round` 只接受 1/2；`report_text.enrich_report` 生成 summary/round_summaries/review_guidance；真实 `failed_after_2`、2 轮、4 薄弱概念、2 来源、16 题；UI 分轮显示 | ✅ |
| 13 动态调整计划 | 🟧 C；🟦 A 核对；🟪 B 提供薄弱点 | 按成绩、薄弱点、未完成任务和修改要求调整，保留已完成任务 | `reschedule_plan` 只移动未完成任务，完成项原样保留；按最新报告薄弱章节优先；`save_rescheduled_plan` 写只读版本；真实计划 3 个版本、UI 历史只读；`test_plan_reschedule.py` | ✅ |
| 14 中途保存与恢复 | 🟪 B；🟦 A 测试；🟧🟩 支撑 | 保存题组、作答、成绩、状态；恢复同一套题；重复提交不重复计分 | `store_round` 不覆盖已存题组；`save_draft`/`save_answer` 分离；`practice_lock` 覆盖整题提交；真实重复提交 200 且两轮成绩不变；刷新恢复同一报告；`test_practice_rounds.py` 并发/重复用例 | ✅ |
| 15 独立问答 | 🟩 D；🟧 C | 带来源页码的讲义问答；无依据时说明；不改变练习成绩 | `agent/qa.py` 仅检索本课程资料，引用页校验；证据不足才网页补充并分开展示；拒绝模板；只读练习状态；真实 UI 问答历史与刷新通过；`test_qa_isolation.py` | ✅ |
| 16 异常与执行记录 | 🟩 D；🟪🟧 处理；🟦 A 核查 | 统一异常、有限重试、耗时与模型用量日志；保存状态 | `agent/llm.py` 重试 1 次；`agent/telemetry.py` 记录 operation/run_id/耗时/token/估算成本（缺单价为 null）；真实会话 27 次调用、44 条操作；`test_telemetry.py` | ✅ |
| 17 持续测试 | 🟦 A；🟪 B；🟧🟩 修复 | 汇总测试、跑完整流程、记录问题与验收结果 | 本轮 284 后端 + 44 模拟浏览器 + 15 真实浏览器 + 真实 MySQL/Milvus + 真实两轮练习；证据文件见下；本轮未发现新缺陷 | ✅ |
| 18 正式评测与复现 | 🟦 A；🟪 B；🟧🟩 协助 | baseline/full 对比、质量、耗时、成本、失败案例、复现 | `evaluation/`、`evaluation_assets/`、40 证据题/40 简答/20 选择/20 场景草稿、空白人工表、采集与评分 CLI 已就绪；v8 开发联调 64/64；**120 次正式运行、两位独立人工标注、引用语义支持率、真实单价未执行** | ⏳ |

## 本轮修复的差距

1. **文档技术描述与实现不一致**：`docs/flow.md` 原写“PDF 用 PyMuPDF 解析”“流程用 LangChain 编排”。实际是 Docling 逐页解析、PyMuPDF 仅校验页数；业务流程由 Python 代码按数据库状态编排，模型调用与工具接口使用 LangChain。已改为与代码一致，避免最终报告与代码互相矛盾。
2. **过期计数**：`docs/STATUS.zh-CN.md` 的“272 项后端 / 12 项警告”是 v6 历史数字。已在 2026-11-13 的验收段写明本轮 **284 项后端、0 错误/13 警告**，并保留历史语境。
3. **验收脚本自身的字段错误**：首次真实重复提交探针把 `question_id` 写成了 `id`，API 正确返回 422（请求校验失败），不是业务缺陷。修正后用 `question_id` 重跑，返回 200 且两轮成绩不变。该脚本已作为可复现工具保留。
4. **新增可复现验收工具**：`backend/tools/acceptance_db_probe.py`（只读 MySQL）、`acceptance_api_probe.py`（只读 API）、`acceptance_live_practice.py`（创建一次真实两轮练习，会调用模型并写入测试账户）、`acceptance_duplicate_probe.py`、`acceptance_session_probe.py`、`acceptance_summary.py`。它们只读取传入的本机私有凭据路径，不把密码写入输出。

**没有改动的业务代码**：`agent/`、`db/`、`grading/`、`ingest/`、`vector/`、`main.py`、`frontend/src/` 均未修改；本轮不引入行为变化，避免为了“有 diff”而改已验证代码。

## 仍需外部条件的部分（第 18 步）

| 项目 | 现状 | 为什么不能由本轮代填 |
| --- | --- | --- |
| 正式 120 次运行 | 开发联调 64/64 已跑；正式 batch 未跑 | 需要冻结配置、真实模型预算和分系统（baseline/full）各 20 场景 × 3 次 |
| 选择题一致率 100% / 简答一致率 ≥80% | 规则与判分已实现；无人工对照结果 | 需要两位成员独立标注与分歧裁决 |
| 引用支持率 ≥85% | 引用页校验已实现；无人工语义标注 | 需要逐条判断来源页是否真正支持事实 |
| 20 场景 ≥18 通过 | 场景模板与判定器已就绪；正式观察为空 | 需要实际运行记录，不能用模拟结果替代 |
| 真实耗时与成本 | 会话 5 有 27 次真实调用的耗时和 token；金额为 `null` | 未提供模型服务单价；未知价格不能当作零成本 |
| 学习时长校准 | 估时是透明启发式 | 需要学习者真实活跃用时数据 |

正式指标的 `official_accepted` 保持 `null`；本报告不把 284、44、15 等检查数写成模型质量指标。

## 复现命令

```powershell
# 后端回归（轻量依赖；不下载 PDF/嵌入运行时）
cd backend
.\.venv\Scripts\python -m unittest discover -s tests -v

# 前端类型、构建、lint
cd ..\frontend
node node_modules\typescript\bin\tsc -b
node node_modules\vite\bin\vite.js build
node node_modules\oxlint\bin\oxlint

# 五套模拟浏览器检查（需 Playwright + Chrome；用构建产物）
$env:CITEPATH_UI_DIST = 'dist'
$env:CITEPATH_BROWSER = 'chrome'
# 若 Playwright 不在 frontend/node_modules：$env:PLAYWRIGHT_MODULE = '<playwright 包目录>'
node tests\practice-ui-smoke.cjs
node tests\feedback-ui-smoke.cjs
node tests\upstream-ui-smoke.cjs
node tests\planning-ui-smoke.cjs
node tests\restoration-ui-smoke.cjs

# 真实只读验收（需要运行中的 API/MySQL/Milvus 和本机私有凭据）
cd backend
.\.venv\Scripts\python tools\acceptance_api_probe.py <私有凭据.json> <真实联调报告.json>
.\.venv\Scripts\python tools\acceptance_db_probe.py

# 真实两轮练习（会创建测试会话并调用模型，勿对正式账户运行）
.\.venv\Scripts\python tools\acceptance_live_practice.py <私有凭据.json> <输出.json> 7 6
```

## 证据文件

证据在交付目录 `outputs/CitePath-Acceptance-2026-11-13-evidence/`：

`backend-tests-284.txt`、`frontend-tsc.txt`、`frontend-build.txt`、`frontend-lint.txt`、`ui-*-ui-smoke.txt`、`live-ui-acceptance.json`、`live-ui-acceptance.log`、`api-probe.json`、`mysql-probe.json`、`milvus-probe.json`、`live-practice-acceptance.json`、`live-practice-acceptance.log`、`duplicate-probe.json`、`session-5-probe.json`、`prior-live-integration-v8.json`、`summary.json`、`screenshots/`，以及索引 `README.md`。

## 结论

按分工表衡量，**软件交付面已完整**：18 步均有实现、接口、界面和回归证据；两轮练习、错题解释、报告、恢复、问答和日志都在真实服务上跑通。剩余的是第 18 步的正式人工评测与外部数据，不是本轮能替代的代码缺口。
