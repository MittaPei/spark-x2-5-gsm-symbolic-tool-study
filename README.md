# Spark-X2.5-4B：GSM-Symbolic 复杂度与原生计算器配对评测

本仓库保存 HER Hack-Astron #6 的可复现评测。核心问题不是“模型会不会做几道算术题”，而是：在模板配平的 GSM-Symbolic `main / p1 / p2` 三档问题上，给 Spark-X2.5-4B 一个受限、可审计的原生计算器，究竟会救回哪些错误，又会不会引入新的错误。

正式结果生成前冻结的完整方法见 [`PROTOCOL.md`](PROTOCOL.md)。最终仓库将保留全部 120 条原始模型轨迹、工具调用与返回、严格评分结果、推理诚信审阅、运行日志和 SHA256 清单，不替换失败样本。

## 设计摘要

| 项目 | 冻结设置 |
|---|---|
| 模型 | `XHToken/Spark-X2.5-4B@5e10fcc0286756aebf7c41dc52c1e42d95c70281` |
| 权重 | 官方原始 BF16，无量化 |
| 数据 | `apple/GSM-Symbolic@93b5b3758d9d9841ffe81d6cd2ae2b030685b078` |
| 样本 | 20 个模板键 × `main/p1/p2` = 60 题 |
| 条件 | 每题各跑一次 `no_tool` 与 `calculator` |
| 主指标 | 严格 numeric pass@1，无法解析一律计错 |
| 工具边界 | 最多 2 次 AST 白名单精确算术调用，不执行生成代码 |
| 推理预算 | 每条轨迹累计最多 4096 assistant completion tokens |

三个 config 使用相同 `(id, instance)` 键来配平模板来源，但其题面不同。因此跨档结果只解释为同模板分层趋势；严格 A/B 配对只发生在完全相同题目的无工具与计算器两臂。

## 选择与本地验证

从固定数据集 checkout 生成清单：

```bash
uv sync --all-extras --locked
uv run python scripts/prepare_selection.py --dataset-root /path/to/GSM-Symbolic
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

选择算法、完整参数、失败处理和统计口径均记录在 [`PROTOCOL.md`](PROTOCOL.md)。数据集金标只从最后一行 `####` 抽取；Apple 提供的 rationale 不作为权威证明。

## 验收证据规划

| Issue #9 要求 | 最终证据 |
|---|---|
| 固定模型与产物 | `evidence/environment.json`、权重 LFS SHA256 |
| 真实执行 | 精确 prompt、全部 raw responses、工具转录与脱敏日志 |
| 可复现 | 锁文件、脚本、镜像 digest、硬件、参数和 seed |
| 诚实指标 | `results/summary.json` 与逐题结果，固定分母和解析规则 |
| 推理诚信 | 全失败/A-B 分歧/工具轨迹及预选样本审阅 |
| 原创与许可 | [`THIRD_PARTY.md`](THIRD_PARTY.md) 和本文件许可说明 |
| 隐私与权重 | CI secret/path 扫描及模型权重扩展名门禁 |

## 许可与责任

本仓库原创代码按 [Apache-2.0](LICENSE) 发布。必要的 Apple GSM-Symbolic 原文摘录仍按 CC BY-NC-ND 4.0 使用，详见 [`THIRD_PARTY.md`](THIRD_PARTY.md)，不受本仓库 Apache-2.0 许可覆盖。本仓库不包含模型权重。

评测允许使用 AI 辅助执行和整理；最终提交者会复核公开结果并对其负责。模型输出只作为待评分、待审阅的实验数据，不作为未经验证的事实。

