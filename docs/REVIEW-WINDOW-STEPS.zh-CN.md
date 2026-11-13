# 浏览器逐题标注：详细步骤

本文给单复核人使用。窗口只负责人工标注，不计算正式指标；`official_accepted` 不会被这个窗口设置。

## 0. 先确认用的是哪份数据

| 目的 | dataset | 空白表 | 能否标证据 claim |
| --- | --- | --- | --- |
| 熟悉界面 / pilot | `evaluation_assets/cohorts/execution-20261112-r2/dataset.json` | 同目录 `annotations/annotator-a.json` | 不能，`predictions=null` |
| 最终单复核人报告 | 真实运行合并后的 `observed-dataset.json` | 针对 observed 重新生成的 `annotator-a.json` | 能，前提是 observed 有 `predictions` |

**准备批次的空白表不能直接用于最终评分**。真实输出合并后必须重新生成：

```powershell
cd backend
python -m evaluation labels "..\logs\observed-dataset.json" --output-dir "..\logs\human-review"
```

这会生成 `annotator-a.json`、`annotator-b.json`（留空）和 `blind-workitems.json`。

## 1. 启动窗口

从仓库根目录：

```powershell
python -m http.server 8765 --bind 127.0.0.1
```

如果 `python` 不可用，换成你平时运行后端的解释器，例如：

```powershell
.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1
```

浏览器打开：

```text
http://127.0.0.1:8765/tools/review-window/
```

不要直接双击 `index.html`（`file://` 会拦截自动载入）；如果已经打开，用页面上的文件选择器。

## 2. 载入最终数据

### 方式 A：查询参数（推荐）

把路径换成实际位置。假设 observed 和标注都在 `backend/logs`：

```text
http://127.0.0.1:8765/tools/review-window/?dataset=../../backend/logs/observed-dataset.json&annotation=../../backend/logs/human-review/annotator-a.json
```

### 方式 B：文件选择器

点右上角：

1. `载入 dataset` → 选 `observed-dataset.json`
2. `载入空白表` → 选 `annotator-a.json`

载入成功后左侧显示 **140** 项，顶部显示 `0 / 140`。

## 3. 填写复核人信息

左侧：

1. `复核人 ID`：填你的名字或课程要求的 ID。
2. 勾选 `独立完成，未参考他人标签`。

不填 ID 或不勾选，导出会被阻止。

## 4. 逐题标注

左侧可以按 `全部 / 未完成 / 选择 / 简答 / 证据` 筛选。当前题右侧显示题干、系统作答、来源页和标注表单。

### 选择题

1. 先自己读题和选项，判断系统作答是否正确。
2. 在“这条选择题的候选答案是否正确”选 `正确` / `错误` / `未判`。
3. 勾选支持页；必要时在下面选 PDF、填页码，点“添加来源页”。
4. 展开“查看候选答案键”只用于审计；先独立判断，再看答案键。
5. 题目审计四项：
   - 题目清晰
   - 来源支持
   - 答案键正确
   - 不重复

### 简答题

1. 看系统作答和 rubric。
2. 勾选命中的 rubric 点；索引从 **0** 开始。
3. 5 点中 4 点通过；3 点不通过；命中比例按 80% 判断。
4. 支持页、题目审计同上。
5. 拿不准先点“标记为未判定”，不要硬填。

### 证据问答

baseline 和 full 是两道独立标注，左侧会显示 `[baseline]` / `[full]`。

1. “问题是否被讲义支持”：支持 / 不支持 / 未判。
2. “答案是否正确”。
3. “claim 是否完整”。
4. 参考点覆盖：勾选参考答案点命中项。
5. Claim 支持：每条 claim 选是/否/未判；如果该 claim 的某条引用不相关，勾“无关引用”。
6. 支持页按需添加。

**如果提示“该变体还没有真实系统输出”**：说明你载入的是准备数据，不是 observed；换数据，不要在准备数据上完成证据 claim 标注。

## 5. 自动保存与中断

- 每次修改后约 0.35 秒自动保存到浏览器本机。
- 刷新页面后，只要 dataset 的 `dataset_sha256` 相同，会恢复进度。
- 换 dataset 会进入另一份进度，互不覆盖。
- 不要清理浏览器站点数据；需要迁移时先导出 JSON。

## 6. 导出

1. 确认 140 项进度；未完成项可以导出部分，但会二次确认。
2. 点右上角 `导出 annotator-a.json`。
3. 浏览器下载 `annotator-a.json`。
4. 不要把它复制成 `annotator-b.json`；B 必须由第二位复核人独立填写。

导出文件会包含：

- `annotator_id`
- `independent: true`
- `label_origin: "human"`
- `dataset_sha256`
- 140 条 `labels`

## 7. 检查导出文件

从 `backend` 运行：

```powershell
python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print('labels',len(d['labels']),'id',d['annotator_id'],'independent',d['independent'],'origin',d['label_origin'],'sha',d['dataset_sha256'])" "<annotator-a.json 的完整路径>"
```

预期：`labels 140`、`independent True`、`origin human`，SHA 与 observed 的空白表一致。

再做一次完整性检查：

```powershell
cd backend
python tools/single_reviewer_pilot.py "..\logs\observed-dataset.json" "..\logs\human-review\annotator-a.json" "..\logs\pilot.json"
```

`label_completion.completed` 应为 140；不足就是还有未填项。

## 8. 生成单复核人报告

有真实 workflow 观察时（示例路径是 `backend/logs`，按实际位置替换）：

```powershell
cd backend
python tools/single_reviewer_report.py "..\logs\observed-dataset.json" "..\logs\human-review\annotator-a.json" "..\logs\single-reviewer-report.json" `
  --workflow "..\logs\workflows-collected.json" `
  --approved-by "你的姓名" --approval-reference "邮件/日期/课程文件" `
  --markdown "..\logs\single-reviewer-report.md"
```

没有 workflow 观察时去掉 `--workflow`；结论会是 `insufficient`，不会伪造通过。

报告字段：

- `official_accepted: null`（协议要求两人，不能改）
- `protocol_deviation`：2 人要求、实际 1 人、批准信息
- `single_reviewer_conclusion`：`pass` / `fail` / `insufficient`
  - 引用支持率 ≥85%
  - 20 场景中至少 18 个通过（每个场景 baseline/full 各 3 次全部匹配）
  - 无第三轮、无重复计分、问答不改成绩

## 9. 写进最终报告的口径

可以写：

> 在课程批准的单复核人偏离下，引用支持率为 X%、流程场景 Y/20 通过、无禁止错误；由于只有一位复核人，未计算双人一致率，`official_accepted` 保持 `null`。

不能写：

> 达到提案的 100% 选择题一致率、≥80% 简答一致率，或完成正式双人验收。

## 10. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 自动载入失败 | 用了 `file://`，或路径不对 | 用 `http://127.0.0.1:8765/...`，或文件选择器 |
| 证据 claim 区域为空 | 用的是准备数据 | 换 `observed-dataset.json` |
| 只有 A 表 | 只有一位复核人 | 按单复核人偏离记录；B 留空 |
| 导出被阻止 | 没填 ID 或没勾独立完成 | 补填后再导出 |
| 进度没恢复 | dataset SHA 变了 | 检查是否换了 dataset/annotation |
| 端口被占用 | 8765 已被占用 | 换 8766 并改 URL |
| PDF 链接 404 | 数据不在仓库根目录下 | 从仓库根目录启动 server，或直接打开 PDF 路径 |

## 11. 时间建议

140 项建议分两个半天：

- A：11-14 10:00–12:00，选择 + 前 20 简答，目标 40/140
- B：11-14 14:00–17:00，剩余简答 + 20 evidence baseline，目标 100/140
- C：11-15 10:00–13:00，40 evidence full + 审计，目标 140/140
- D：11-15 15:00–16:00，回看与收尾

每 50 分钟休息 10 分钟；连续不超过 3 小时。
