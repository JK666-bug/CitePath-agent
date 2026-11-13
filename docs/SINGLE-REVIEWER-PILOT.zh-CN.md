# 只有一位复核人时的处理办法

## 先说结论

**一位复核人不能完成正式评测。** 提案和本项目的评估协议要求两位成员独立标注、再共同裁决分歧；代码会把缺少第二份独立人工表的状态保持为 `pending`，`official_accepted` 保持 `null`。不能把同一个人的两次填写、AI 预标注或复制表格当作第二位复核人。

只有一位复核人时，可以做的是**单复核人 pilot**：把流程和指标跑通，得到描述性结果，但不能写成正式验收结论。

## 现在就能做：单复核人 pilot

适用：只有一位成员能投入时间，但希望先检查 140 个工作项、判分边界和引用支持情况。

1. 这位复核人独立完成 `annotator-a.json`，不要看 `assistant-review-hints.json`。
2. 不要填写 `annotator-b.json`；留空，明确记录第二人未参与。
3. 用工具生成描述性报告：

```powershell
cd backend
python tools/single_reviewer_pilot.py <dataset.json> <annotator-a.json> <output.json>
```

输出固定包含：

- `status: "single_reviewer_pilot"`
- `official_accepted: null`
- `reviewer_count: 1`
- `label_completion`（完成/140）
- MCQ 正确率、简答通过率与平均得分点覆盖、证据支持率、答案正确率、claim 支持率、参考点覆盖率、题目审计通过率
- `limitations`：无复核人一致性、无裁决、不能作为正式结果

这个报告可以用于内部检查、发现问题、准备答辩，**不能用于声称达到提案的 100% / 80% / 85% / 18-of-20 目标**。

## 推荐：尽快补第二位复核人

优先找一位**没有参与标注**的成员或同学。一个人完成 140 项大约需要 4–8 小时（取决于证据题需要回看多少页）；第二位复核人不需要写代码，只需要：

1. 拿到同一份 `observed-dataset.json` 和原始 PDF；
2. 独立填写 `annotator-b.json`，完成前不要看 A 的标签；
3. 填写自己的 `annotator_id`，设 `label_origin: "human"`、`independent: true`；
4. 再和 A 一起裁决分歧。

第二位复核人到位后，正式流程仍是：

```powershell
python -m evaluation adjudication <observed-dataset.json> --annotator <a.json> --annotator <b.json> --output-dir <review>
python -m evaluation score <observed-dataset.json> --annotator <a.json> --annotator <b.json> --adjudication <review/adjudication.json> --usage-log <model-usage.jsonl> --output <report.json>
```

`score` 只有在两份独立人工表、完整观察和裁决都满足时才可能给出 `official_accepted: true`。

## 如果课程/老师同意单人复核

如果这是**明确批准的协议偏离**，可以把单人复核作为最终交付，但报告必须保留偏离记录，并继续把 `official_accepted` 写成 `null`；另用 `single_reviewer_conclusion` 表示单人结论。

先由复核人完成 `annotator-a.json`，再在真实 120 次观察合并后运行：

```powershell
cd backend
python tools/single_reviewer_report.py <dataset.json> <annotator-a.json> <report.json> `
  --workflow <workflow-observations.json> `
  --approved-by "<批准人>" --approval-reference "<邮件/日期/课程文件>" `
  --markdown <report.md>
```

报告会记录：

- `status: "single_reviewer_evaluation"`
- `official_accepted: null`（协议要求两人，不能改）
- `protocol_deviation`：需要 2 人、实际 1 人、批准人和批准依据（没填则 `pending`）
- `single_reviewer_conclusion`：`pass` / `fail` / `insufficient`，按引用支持率 ≥85%、20 场景中至少 18 个通过、无禁止错误判断
- MCQ 正确率、简答通过率、claim 支持率等描述性指标
- 限制：没有复核人一致性、没有裁决，不能声称达到原协议的双人一致率目标

可以写进最终报告的说法：

> 在课程批准的单复核人偏离下，引用支持率为 X%、流程场景 Y/20 通过、无禁止错误；由于只有一位复核人，未计算双人一致率，`official_accepted` 保持 `null`。

不能写进最终报告的说法：

> 达到提案的 100% 选择题一致率、≥80% 简答一致率或完成正式双人验收。

## 不能做的事

- 不要把 A 的标签复制成 B；代码能检查 ID 重复和 `independent` 声明，但无法证明独立性，复制会破坏学术诚信。
- 不要把 AI 预标注当作第二份人工表；它只能作为候选提示，且不能写入 `label_origin: "human"`。
- 不要因为有一个人复核就修改通过阈值、场景数或 `official_accepted`。
- 不要用单复核人 pilot 的数字替代提案目标。

## 如果最终确实只有一位复核人

这属于**协议偏离**，需要课程教师/助教明确同意；在获得同意前，项目只能报告：

- 单复核人描述性结果；
- 正式指标 `pending`；
- `official_accepted: null`；
- 明确写出“未满足两位独立人工复核的提案要求”。

本项目的正式评分器不会因为人数不足而放宽门槛；这是有意的保护。
