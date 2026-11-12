# 上游更新后的评估准备批次

本批次绑定已提交的应用代码 `2996a19`，接入上游 `2b37b92` 后重新记录模型提供方、模型名称、接口地址指纹、源文件哈希和完整已安装依赖版本。原批次 `evaluation_assets/final` 保留不动，不能把它的冻结配置冒用于新版本。

120 条问题/输入仍是此前 AI 编写的待人工复核草稿，不是真实学生数据；原讲义、候选答案与评分点未因本次代码更新改写。此批次的全部系统预测仍为 `null`，两份独立人工表各 140 项均为空，120 次工作流运行表为空，章节映射未观察。`evaluation-status.json` 保持 `pending`、`official_accepted: null`。

`frozen-configuration.json` 是无模型请求的准备快照，尚无有效模型密钥、运行中的数据库服务或实际推理结果。正式采集前在真实完整服务环境重新冻结为新的命名批次。不要直接在本准备批次补造运行记录。

提案以第 4、6、8 讲各作为一个评估章节；应用可以将一讲拆成多个教学主题。`chapter-mapping.template.json` 故意保持空白，实际生成后须记录稳定章节 ID、执行顺序并独立复核，才能按提案执行正式对照。

所有 `pdf_path` 从仓库根目录解析，讲义原件位于 `data/mit-6.006-spring-2020`。开发仅用第 2、3 讲。此处问题、答案、人工表及旧目录的机器候选提示不得进入讲义检索库；独立标注者不要先查看机器提示。

从 `backend` 可执行：

```powershell
python -m evaluation validate ../evaluation_assets/cohorts/upstream-20261112/dataset.json
python -m evaluation score ../evaluation_assets/cohorts/upstream-20261112/dataset.json --output logs/preparation-pending.json
```

完整协议和实际开发联调命令见 `docs/EVALUATION.md` 与 `docs/LIVE-INTEGRATION.md`。开发联调脚本不是最终 120 次 baseline/full 对照采集器，也不能替代两位成员的独立人工评价。

当前采集器/归档恢复版本的新准备批次位于 `../execution-20261112`。本旧批次仍未采集；真实运行协议变化不能套用其旧配置。
