# 最终评估资料准备包

本目录按提案准备了 **120 条 AI 编写的待复核草稿**：20 个选择题作答、40 个简答作答、40 个证据问答（30 个拟可回答、10 个拟不受所选讲义支持）和 20 个流程场景。输入作答是编写的测试案例，不是真实学生数据。所有系统预测目前为 `null`。

讲义原件和 SHA-256 在 `data/mit-6.006-spring-2020/corpus.json`；仅使用第 4、6、8 讲作为本目录的最终评估来源，第 2、3 讲留作开发。保留原 PDF 页码，不把最后的归属页当成教学证据。

`dataset.json` 是问题与输入数据草稿。选择题 `answer_key`、简答 rubric 和证据问题的参考点都是候选参考，需要两位成员独立检查。`assistant-review-hints.json` 是机器辅助候选提示，不能冒充独立人工标签；独立标注时请不要先查看该提示文件。

后端评估 CLI 可以生成两份空白的独立标注表及去除系统判分的工作材料。每位标注者各自完成自己的副本，再共同复核分歧。不要把一个人的标签复制为另一人的结果，不要将空白、未运行或模型失败填成零分或通过。

```powershell
# 从 backend 运行；把 python 换成实际虚拟环境的解释器。
python -m evaluation validate ../evaluation_assets/final/dataset.json
python -m evaluation labels ../evaluation_assets/final/dataset.json --output-dir ../evaluation_assets/final/annotations
python -m evaluation preflight --output logs/live-preflight.json
python -m evaluation score ../evaluation_assets/final/dataset.json --output logs/evaluation-pending.json
```

在实际模型、MySQL、Milvus 和 API 准备好以后，先冻结真实运行环境，再运行评分收集和真实流程。对比 baseline 与完整系统时保持第一轮题目、作答、模型、材料和反馈一致；每个流程场景每个系统执行三次。20 个场景中的计分注入用于独立验证控制规则，真实端到端场景的通过状态需从实际 grader 返回成绩计算，不能强迫模型命中预设分数。

生成正式标签之前应先收集实际系统预测。预测改变后，数据快照 SHA-256 会改变；重新生成绑定新快照的标注工作文件。目录附带的空白表仅是当前准备快照，不表示已完成对未产生的回答进行人工评价。

没有有效模型配置或两位独立人工判断时，工具必须保持 `pending` 和 `official_accepted: null`。测试通过数量不能替代提案的真实评分一致率、引用支持率或实际工作流成功率。完整协议见 `docs/EVALUATION.md`。
