# 验收工具

这些脚本用于 2026-11-13 的 18 步分工验收，证据和结论见
[18 步分工验收](../../docs/ACCEPTANCE-2026-11-13.zh-CN.md)。

| 脚本 | 作用 | 是否写入/调用模型 |
| --- | --- | --- |
| `acceptance_db_probe.py` | 只读统计 MySQL 的资料、页面、会话、题目和作答数量 | 否 |
| `acceptance_api_probe.py` | 用本机私有凭据登录，只读核对课程、计划、资料、报告、问答和运行身份 | 否 |
| `acceptance_live_practice.py` | 在指定课程/章节新建一次真实两轮练习并核对结束、报告和重复提交；**会创建测试数据并调用模型** | 是 |
| `acceptance_duplicate_probe.py` | 对已完成的真实练习再次提交，核对成绩不变 | 否 |
| `acceptance_session_probe.py` | 读取指定会话的判分、解释状态和模型/操作日志 | 否（只读日志和数据库） |
| `acceptance_summary.py` | 把指定证据目录（默认仓库根 `evidence/`）汇总成 `summary.json` | 否 |
| `formal_batch_manifest.py` | 从冻结数据集和运行时绑定生成 20 场景 × 3 次 × 2 系统的 120 次运行核对表 | 否 |
| `single_reviewer_pilot.py` | 用一份人工表生成**描述性**单复核人 pilot；`official_accepted` 固定为 `null` | 否 |
| `single_reviewer_report.py` | 有课程批准的单人偏离时，生成带 `protocol_deviation` 的单复核人报告；仍不设置 `official_accepted` | 否 |

不要在正式账户上运行 `acceptance_live_practice.py`。凭据路径作为命令行参数传入，
脚本不会把密码、Cookie、题干、答案或提供方错误写入输出。数据库和向量库的默认
连接参数与 `backend/db/connection.py` 一致，可用 `MYSQL_*` 环境变量覆盖。
