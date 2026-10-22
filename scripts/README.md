# 脚本索引

所有脚本都以**项目根目录**为工作目录运行（脚本内部按 `__file__` 反推根目录，不依赖 cwd 设置，
但路径参数与输出目录是相对根目录的）：

```bash
.venv/Scripts/python.exe scripts/<分类>/<脚本>.py [参数]
```

## `data/` — 演示数据生成与灌库

| 脚本 | 用途 |
| --- | --- |
| `generate_medical_docs.py` | 14 份多科室合成文档的生成/校验。**默认只校验**（逐份比对字数与章节数），`--write` 强制写出，`--sync` 以磁盘现有内容为准回写脚本（幂等，改完文档后跑一次） |
| `expand_medical_docs.py` | 把 `data/medical_docs/*.md` 的最新内容同步进知识库并重跑解析入库；`--dry-run` 只看计划 |
| `seed_medical_kb.py` | 批量灌入演示知识库（同名文档跳过，可重复执行）。`--username` 必填，填你自己的登录账号 |
| `generate_training_handbook.py` | 生成主演示文档《医院员工培训守则》PDF（7 页，含 CPR 流程图与 8 张表格） |
| `make_scan_pdf.py` | 造一个「部分页面被栅格化」的 PDF，用来回测多模态 OCR 兜底链路，如 `--pages 4,5` |
| `generate_sample_data.py` | 生成 md / pdf / pptx / png 四种格式的解析回归样本，不参与默认演示流程 |
| `legacy/generate_staff_handbook.py` | 早期简版手册生成脚本，**保留备查**，与 `generate_training_handbook.py` 输出同名文件，一般不要运行 |

## `eval/` — 检索与问答质量评测

| 脚本 | 用途 |
| --- | --- |
| `eval_ragas.py` | RAGAS 四指标（精确度 / 召回率 / 忠实度 / 相关性）。`--stage run\|regen\|judge\|all`、`--cases`、`--resume`、`--workers`、`--judge-model` |
| `eval_retrieval_only.py` | 纯检索评测：只跑召回与命中位次，不调用大模型，秒级出结果 |
| `ragas_report_html.py` | 把 `scores_*.json` 渲染成单文件 HTML 看板 |
| `check_retrieval.py` | 单次检索诊断：打印命中资料与相关度，用于扩充文档后快速确认跨科室命中情况 |

常用组合：

```bash
# 20 条快评（约 12 分钟）
python scripts/eval/eval_ragas.py --stage all --cases data/eval/ragas_cases_20.json --tag quick

# 只补算上次被限流打掉的指标，不重复判定已完成的样本
python scripts/eval/eval_ragas.py --stage judge --from data/eval/run_quick.jsonl \
    --resume data/eval/scores_quick.json --tag quick

# 检索回测（不花钱、不看大模型脸色）
python scripts/eval/eval_retrieval_only.py --top-k 3 --rerank
```

## `bench/` — 连通性、耗时与容量

| 脚本 | 用途 |
| --- | --- |
| `check_llm.py` | 模型连通性自检：逐个试候选模型，区分「欠费 / 未授权 / 限流 / 正常」；`--key` 可临时换 Key 不写 `.env` |
| `bench_thinking.py` | 对比「深度思考」开/关的首字延迟与总耗时 |
| `capacity_probe.py` | 单机 CPU 上 bge-m3 / bge-reranker 的延迟与并发退化，用来估算能同时支撑多少人问答；只读 |
| `smoke_e2e.py` | 端到端冒烟：注册 → 建库 → 上传四类文档 → 流式问答；需后端已启动且 `DEBUG=true` |

## `ops/` — 运维与迁移

| 脚本 | 用途 |
| --- | --- |
| `reindex_all.py` | 重跑全部已完成文档的解析入库，补齐父块与图片；改了切块/解析逻辑后跑一次 |
| `rebuild_collection_parent_fields.py` | Milvus 2.4 不支持加字段，用它「备份 → 删集合 → 重建 schema → 重新入库」 |
| `migrate_shared_collection.py` | 由「每库一个集合」迁移为「共享集合 + `kb_id` 隔离」 |
| `migrate_parent_blocks.py` | 历史数据补父块（`parent_id` / `parent_content`） |
| `migrate_qa_schema.py` | 问答缓存表结构升级 |
| `migrate_media_columns.py` | 媒体列（图片 URL / 图注）结构升级 |
| `migrate_media_to_qiniu.py` | 本地图片批量搬迁到七牛云对象存储 |
| `migrate_milvus_dynamic.py` | Milvus 动态字段迁移（`images` 等） |
| `qa_cache_tool.py` | 问答缓存运维：`stats` / `rebuild` / `prune` / `import` / `bench` |
