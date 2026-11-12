# CitePath 前后端对接说明

核对日期：2026-11-12。已兼容最新上游的模型配置、规划和问答历史变化。当前 React 前端连接规划、练习、考试、报告与问答 API；界面演示仍是独立的固定样例。接口实现不等于已完成真实数据库、向量库和模型的端到端验收，完整状态见 [功能核对](../docs/STATUS.zh-CN.md)。

## 调用与登录

前端通过 `src/shared/request.ts` 发起 `/api/...` 请求，保留 `credentials: 'include'`。开发时 Vite 代理到 `http://127.0.0.1:8000`；生产部署需配置自己的 `/api` 转发。后端使用 HttpOnly `citepath_session` Cookie；模型密钥只放在后端配置中。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/register`、`/api/login`、`/api/logout` | 注册、登录、退出 |
| GET | `/api/me` | 恢复登录状态 |
| GET / POST | `/api/courses` | 课程列表、创建课程 |
| GET / DELETE | `/api/courses/{course_id}` | 课程详情、删除课程 |
| POST | `/api/courses/{course_id}/documents` | multipart 单个 PDF 上传，字段 `file` |
| GET | `/api/courses/{course_id}/documents/{document_id}/file` | 有所有权检查的原始 PDF 查看/下载 |
| DELETE | `/api/courses/{course_id}/documents/{document_id}` | 归档资料，保留 ID、原 PDF 与历史 |
| GET | `/api/courses/{course_id}/documents/inventory` | 有所有权校验的在用/归档资料及原文件可用状态 |
| POST | `/api/courses/{course_id}/documents/{document_id}/restore` | 校验原 SHA-256、重建向量后恢复原 ID |
| GET | `/api/courses/{course_id}/evaluation/runtime` | 登录后读取本课程的无密钥运行配置与资料哈希证明 |
| GET / POST | `/api/courses/{course_id}/plan` | 读取计划、首次生成或重新排期 |
| GET / POST | `/api/courses/{course_id}/plan/requirements` | 读取或核对规划输入，缺项返回补充问题 |
| GET | `/api/courses/{course_id}/plan/versions` | 只读版本列表 |
| GET | `/api/courses/{course_id}/plan/versions/{version}` | 查看不可修改的历史快照 |
| POST | `/api/courses/{course_id}/plan/tasks/{task_id}/complete` | 完成任务 |
| POST | `/api/courses/{course_id}/chapters/{chapter_id}/practice` | 开始或恢复章节练习 |
| GET | `/api/courses/{course_id}/practice/{session_id}` | 恢复原题组、当前题、草稿、成绩和状态 |
| PATCH | `/api/courses/{course_id}/practice/{session_id}/draft` | 保存当前题草稿，不判分 |
| POST | `/api/courses/{course_id}/practice/{session_id}/answer` | 提交当前题并判分，推进轮次或结束 |
| GET | `/api/courses/{course_id}/chapters/{chapter_id}/reports` | 历史章节练习和考试报告 |
| POST | `/api/courses/{course_id}/chapters/{chapter_id}/exams` | 创建独立章节考试 |
| GET | `/api/courses/{course_id}/exams/{exam_id}` | 恢复考试或读取考试结果 |
| POST | `/api/courses/{course_id}/exams/{exam_id}/drafts` | 保存考试草稿 |
| POST | `/api/courses/{course_id}/exams/{exam_id}/submit` | 提交考试 |
| GET / POST | `/api/courses/{course_id}/questions` | 历史问答、独立提问 |

`GET /api/health` 仅检查 API 响应；`GET /api/agent/ping` 会实际调用模型。健康接口成功不能证明 MySQL、Milvus、PDF 解析或模型可用。

## 入库与资料来源

课程详情的 `documents[]` 包含 `id`、`position`、`filename`、`ingest_status`、`ingest_error`、`page_count` 和 `usable_page_count`。

上传使用内容哈希去重。关系数据先提交，向量写入和 flush 成功后才发布 `complete`；失败显示 `failed` 和可操作的 `ingest_error`。重传相同 PDF 会复用原文档并重试索引，不重新创建课程。新题生成会校验状态和向量存在性；已有题目、草稿、成绩与报告恢复不要求重新调用向量库。

来源对象使用真实 `document_id` 和原始 `page_number`，可附带界面文档序号 `position` 和 `filename`。文档序号用于展示，权限检查和数据关联使用 `document_id`。删除资料与跨存储清理尚不构成分布式原子事务。

原始 PDF 默认保存到 `backend/storage/uploads`，可用后端变量 `PDF_STORAGE_DIR` 指定持久目录。原文件在向量索引前原子写入；文件名只用数据库整数 ID。查看接口检查当前用户与课程归属，引用链接可加 `#page=原始页码`。早期上传记录可能没有原文件，接口返回 404 时重传同一 PDF 可补回；不能从纯文本页面记录重建原文件。

移除单份资料现在是明确归档：保留行、原 PDF、内容哈希和历史引用，`is_active=0`、`removed_at` 记录时间、展示位置设为空。归档来源仍可从历史打开；新规划、检索、问答记忆和新题生成排除它。恢复必须匹配原文件哈希，向量 flush 成功后才重新激活，失败保留归档状态供重试。删除整个课程仍永久清理其文件与记录。

来源弹窗先查询 inventory，按稳定 document ID 核对原文件及原始页号；旧版本已经物理删除的 ID 显示不可用，新的上传不冒充旧来源。inventory 返回 `active`、`removed_at`、`sha256`、`original_pdf_available` 和 `page_numbers` 等字段。

独立问答的可选 `evaluation_context` 包含 `evaluation_id`、`system`（baseline/full）、`item_id`，仅专用测试账号可提交，用于记录模型用量。普通前端不需要该字段。运行证明接口核对启动时和当前源码/模型配置，发生漂移时要求重启；它不返回 API 密钥或原始服务地址。

## 首次规划与重新排期

`POST /plan` 请求：

```json
{"start":"2026-11-12","end":"2026-12-01","note":"Focus on graph search","profile":{"goal":"Prepare for the exam","prior_knowledge":"Beginner","daily_minutes":60,"reading_words_per_minute":180}}
```

首次请求读取已完成入库的讲义，以模型生成章节、概念、引用页和日期任务。返回 `{ "status": "ready", "plan": ... }`，计划包含 `version`、`start`、`end`、`reason`、`chapters`、`tasks`。任务拥有稳定 ID、章节 ID、类型、日期、完成状态和来源。

显式提供的 `profile` 缺少目标、先修知识或每日分钟数时，返回 HTTP 200 的 `status: needs_input`、`questions`、标准化 `profile` 和已有 `plan`，不调用规划模型。每日分钟数为 1–1440 的整数，阅读速度为 1–1200 的有限数值。旧客户端省略 `profile` 时采用保存值或明确记录的默认假设。

已有计划再次请求会重新排期，保留章节边界与 ID、已完成任务完整快照、已存题目和报告，只调整未完成任务。最新正式练习报告中的薄弱章节优先，其后参考备注关键词；普通重新排期不调用模型或向量检索。课程级命名锁覆盖规划过程，发布时再次校验版本和资料指纹，并发完成任务使用行锁保护。

`GET /plan` 和成功发布返回 `material_update: {new_page_count,new_document_ids,missing_document_ids,can_update}`。新资料不会自动重建旧章节；明确发送 `update_materials: true` 和当前 `expected_version` 才增量解析尚未纳入的教学页。每份 PDF 独立划分主题；旧章节、概念、完成任务和报告保持。版本或资料变化返回 HTTP 409，前端重新加载最新计划，输入仍可修改后重试。

计划包含 `planning_profile`、`estimated_total_minutes`、`estimated_remaining_minutes`、`estimate_basis` 和 `capacity`；章节及任务提供 `estimated_minutes`。估时根据实际教学文本、阅读速度和概念练习开销计算，界面标明启发式假设，展示每日预算及超额警告。旧的已完成任务不补写估时，缺失值不冒充零分钟实测结果。

版本列表返回 `{versions:[{version,reason,created_at,change_type}],read_only:true}`；单版本返回 `{version,plan,saved_at,change_type,read_only:true}`。生成、排期、增量资料和首次完成任务均保存不可覆盖的版本，重复完成不增加版本；历史界面仅查看，不恢复或覆盖当前计划。

## 章节练习协议

开始练习的请求体可省略，默认通过线为 80%；也可发送：

```json
{"passing_threshold":0.9}
```

通过线范围为大于 0 且不超过 1，在新会话建立后固定。恢复已有会话不会更改它。简答题的得分点命中门槛始终是 80%，与章节通过线分别处理。

服务端先原子保存整轮题组，再逐题呈现。草稿与提交均使用：

```json
{"question_id":123,"response":"Student answer"}
```

`PATCH /draft` 只保存，不改变成绩。`POST /answer` 判分后返回当前会话；成功处理过的同一题再次提交返回已保存状态，不重复评分。模型超时、批改缺项或非法结果报错并保留题目/草稿，前端展示重试；不得用本地默认值补成“答错”。

会话包含 `round_number`、`passing_threshold`、`answered_count`、`round_question_count`、`round_results`、当前 `question`、最近 `feedback` 和最终 `report`。第一轮未通过时，只针对薄弱概念生成第二轮；第一轮通过直接结束，第二轮无论结果如何都结束，不生成第三轮。

报告中的 `rounds` 分别记录每轮 `correct_count`、`total`、`accuracy`、显示用 `score` 和 `passed`。不合并或平均两轮分数。`outcome` 为：

| 值 | 含义 |
| --- | --- |
| `passed_round_1` | 第一轮通过 |
| `passed_round_2` | 第二轮通过 |
| `failed_after_2` | 两轮后仍未通过 |
| `legacy` | 旧规则历史记录，不冒充新规则正式结果 |

最终报告还包含 `remaining_weak_concepts`、`remaining_sources` 和错题详情。正确题不请求补救解释。前端以服务端状态为准；独立章节考试是另一条功能路径，不承担练习的两轮流转。

## 错题解释恢复与报告说明

`POST /practice/{session_id}/questions/{question_id}/explanation/retry` 和
`POST /exams/{exam_id}/questions/{question_id}/explanation/retry` 分别返回更新后的完整练习/考试记录，不需要请求体。接口验证当前登录用户的所有权及题目归属，仅为已提交的错题补生成解释。

解释字段为 `explanation_status`（`not_required/pending/failed/ready`）、`explanation_error` 和 `explanation_attempts`。有效分数先保存；解释失败不会重新判分，重试只更新解释及对应报告文字，不改变轮次、通过结果、原题或完成时间。正确题和已成功解释的题目不会再次调用模型。

简答报告包含 `rubric`、`rubric_hits`、`points_hit` 和 `points_total`。旧记录没有逐点命中索引时返回 `null`，界面不从总分猜测命中了哪些点。报告增加 `summary`、`round_summaries`、`review_guidance` 和 `feedback_pending_count`；这些文字仅来自已保存的成绩、概念与来源。

## 独立问答

`POST /questions` 接收 `{ "question": "..." }`；`GET /questions` 读取历史记录。讲义问题先检索本课程资料；讲义证据不足时可补充网页来源，回答与界面区分 `cited_pages` 和 `web_sources`，不把外部网页包装为讲义页。学习记录问题只读取当前用户的真实练习/考试数据；官方章节通过与概念掌握是不同字段。

问答只读练习状态，不改变成绩、当前轮次或通过结果。引用范围校验已实现，但引用内容是否语义支持每个事实仍需正式人工评估。

## 本地验证

按根目录 [README](../README.md) 启动服务。后端回归测试使用 `python -m unittest discover -s tests -v`；前端运行 `npm ci`、`npm run build` 和 `npm run lint`。测试中的模拟 MySQL/Milvus/模型只验证程序行为；真实联调还需检查 Docker、有效模型配置和真实 PDF。

固定界面文案为英文；用户备注、文件名和讲义原文保留原语言。练习题遵循讲义语言生成。`Interface demo` 不写入真实课程数据，不能作为真实学习效果或正式验收结果。
