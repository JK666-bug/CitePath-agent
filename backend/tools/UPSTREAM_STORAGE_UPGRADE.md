# 2026-11-18 存储兼容与索引升级

现有 MySQL 数据通过增量列迁移保留：documents 增加 kind、parent_id、answer_mode；practice_sessions 增加 prefs_json，已有 workflow_version、通过线、成绩和草稿不变。资料归档保留 ID、页面和原 PDF。样卷及答案独立于活动讲义过滤，归档样卷不会继续参与出题。

PDF 可同时读取旧的 `storage/uploads/{document_id}.pdf`（或 PDF_STORAGE_DIR）和上游的 `data/pdfs/{course_id}/{document_id}.pdf`。本次无须搬动原文件；部署时须继续挂载原 PDF 目录，并保留任何已有的新目录。新上传沿用旧的原子保存方式。不要删除旧目录。

向量代码不会因为 schema 不匹配而删除集合。旧的 sparse/vector 混合索引继续使用；新写入在旧 schema 下只保存普通页面块，避免无法记录 bridge_to 时产生跨页引用错误。新建集合包含 bridge_to，启用完整的跨页桥接检索。不支持的更旧 schema 返回明确错误并保留原集合。

如需升级桥接索引，在 **backend 目录**、使用项目完整环境执行：

```powershell
python tools/rebuild_vector_index.py --target lecture_segments_v2_20261118 --output rebuild-plan.json
python tools/rebuild_vector_index.py --target lecture_segments_v2_20261118 --apply --output rebuild-result.json
```

命令读取 backend/.env 的数据库和 Milvus 配置，但不显示密钥。默认仅检查和输出计划；`--apply` 只建立一个新的、尚不存在的目标集合，不修改 MySQL 文档或当前集合。重建完成后验证活动完整文档均有索引，并复核源资料指纹。重建期间若资料变化则报错，原集合继续使用；已建立的目标留作诊断，下一次请选择新名称。

重建成功后先验证旧讲义、样卷和跨页检索，再将 API 的 `MILVUS_COLLECTION` 指向目标并重启。保留原集合和原配置，出现问题时将变量恢复原值即可回退。重建工具不会自动切换，也不会删除任何集合。不要在尚未完整重建的目标上启动正式问答。

迁移前保存 MySQL 备份、Docker 卷备份及原 PDF。代码兼容不替代数据备份。正式评估须记录所用集合、源码、样卷和配置，重新冻结整合版本。
