# 正式评测准备（2026-11-13）

本文件记录第 18 步的软件准备状态。它不是正式评测结果：`official_accepted` 仍为 `null`。

## 本轮已准备

- 数据集：`evaluation_assets/cohorts/execution-20261112-r2/dataset.json`，校验通过；120 项（20 选择 / 40 简答 / 40 证据问答 / 20 流程）。
- 两份空白独立标注表：各 140 项，`annotator_id=null`、`independent=false`、`label_origin=unassigned`。
- 120 次运行批次：20 场景 × 3 次 × 2 系统，全部 `not_run`。
- 运行时绑定模板：账号、课程、章节 ID 全部为 `null`，只保留环境变量名。
- 章节映射模板：空白，待真实应用章节生成后填写并独立复核。
- 未完成评分报告：状态 `pending`，`official_accepted: null`。
- 人工复核包和执行清单：在交付目录 `outputs/CitePath-Formal-Evaluation-2026-11-13/`。

## 关键文件

| 文件 | 位置 |
| --- | --- |
| 执行清单 | `outputs/CitePath-Formal-Evaluation-2026-11-13/FORMAL-EVAL-CHECKLIST.zh-CN.md` |
| 准备包索引 | `outputs/CitePath-Formal-Evaluation-2026-11-13/README.zh-CN.md` |
| 人工复核包 | `outputs/CitePath-Formal-Evaluation-2026-11-13/human-review-packet/` |
| 120 次核对表 | `outputs/CitePath-Formal-Evaluation-2026-11-13/run-batch.csv` |
| 运行时绑定 | `outputs/CitePath-Formal-Evaluation-2026-11-13/runtime-bindings-2/` |

## 仍需外部条件

正式 120 次运行、两位成员独立标注与裁决、引用语义支持率、真实价格成本和学习时长校准。完整协议见 [评估说明](EVALUATION.md) 和 [正式采集](FORMAL-COLLECTION.md)。

如果目前只有一位复核人，见 [单复核人 pilot](SINGLE-REVIEWER-PILOT.zh-CN.md)：只能生成描述性结果，`official_accepted` 仍为 `null`，不能替代两位独立人工复核。复核时间安排见 [复核窗口](REVIEW-WINDOW.zh-CN.md) 和 `review-window.ics`。
