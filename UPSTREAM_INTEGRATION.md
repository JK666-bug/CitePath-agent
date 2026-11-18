# 2026-11-18 上游兼容整合

本版本将本地两轮学习流程与 develop 的 c8098dc 合并。练习继续保留固定通过线、最多两轮、草稿、每轮成绩、重复提交保护和独立解释重试，并增加偏好及样卷参考。计划保留学习档案、资料增量、版本检查和历史，新增讲义选择；已有计划纯重排不要求当前仍有活动 PDF，也不因选择变化移除历史章节。

新上游的笔记/cheatsheet PDF、原 PDF 阅读、分会话问答和样卷/独立答案上传保留。问答没有 document_ids 的旧请求默认使用全部可读讲义，显式空列表表示聊天；评估采集器明确发送冻结语料 ID。修复了网页补充问答缺少 invoke_json 导入的问题。

## 安装与验证

在独立 Python 环境安装 backend/requirements.txt；本 Windows 主机使用 backend/requirements-windows.txt 中的原生依赖约束。轻量单元测试使用 requirements-test.txt。新 QA 要求 LangChain 1.5.0、langchain-core 1.8.0、LangGraph 1.2.22，不能直接沿用升级前的虚拟环境。

```powershell
cd backend
python -m pip install -r requirements-windows.txt
python -m pip check
python -m unittest discover -s tests
cd ../frontend
npm ci
npm run build
npm run lint
```

浏览器兼容检查位于 frontend/tests，使用专门假数据验证界面与请求协议；它们不构成真实模型质量评估。实际服务测试必须使用独立数据库、Milvus 集合和 PDF 目录，避免将测试夹具写入现有用户数据。

## 旧数据与切换

先备份 MySQL、向量集合及原 PDF。数据库使用增量列迁移；原 PDF 同时兼容两个存储目录。Milvus 旧 sparse/vector 集合可以继续读取和写入普通块，不会被自动删除。完整跨页检索通过显式建立新集合升级，步骤见 [存储升级说明](backend/tools/UPSTREAM_STORAGE_UPGRADE.md)。重建工具不会自动切换，旧集合留作回退。

后端保留 backend/.env.example 的空密钥模板。实际 key 只放本机 backend/.env；上传源码时排除配置、虚拟环境、node_modules、数据库/PDF 运行数据和日志。

## 评估边界

整合后的源码、依赖和检索集合需要重新冻结。冻结配置新增 retrieval_configuration，切换集合或 Milvus 地址后旧配置校验失败。原有正式评分默认不启用样卷参考，不能用它声称样卷模式已经通过评估。

保留历史评估文件仅用于追溯；不把旧运行结果冒充本版本结果。人工标注、裁决和最终正式评估仍需按项目已确认的协议及明确记录的批准偏离，使用新冻结配置完成；自动化测试或模型不能代替成员的独立判断。
