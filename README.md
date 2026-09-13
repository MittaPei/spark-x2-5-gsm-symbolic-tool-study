# Spark-X2.5-4B：原生计算器何时帮忙，何时添乱？

[![Verify evaluation](https://github.com/MittaPei/spark-x2-5-gsm-symbolic-tool-study/actions/workflows/verify.yml/badge.svg)](https://github.com/MittaPei/spark-x2-5-gsm-symbolic-tool-study/actions/workflows/verify.yml)

这是 HER Hack-Astron #6 的一项可复现案例研究。结论先说：在 60 道
GSM-Symbolic 分层样本上，直接解题策略得到 **45/60（75.00%）**，要求调用
原生计算器的策略得到 **35/60（58.33%）**。样本内下降 16.67 个百分点，但三个
config 的配对检验经 Holm 校正后均不显著，因此不能外推成“计算器会降低模型
能力”。

真正值得注意的是失败发生在哪里：60 条计算器策略轨迹中，模型只在 40 条里
实际调用了工具；63 次调用全部被安全执行器成功计算，执行器错误为 0。可是 23 条
轨迹用满两次调用额度，其中 18 条在工具 schema 撤除后仍输出文字化的第三个
`<tool_call>`，没有交付 `FINAL_ANSWER`。也就是说，这次观察到的主要瓶颈不是
计算器算错，而是**策略遵循、调用预算与答案交付协议之间的失配**。

## 实验设计

| 项目 | 冻结设置 |
|---|---|
| 模型 | `XHToken/Spark-X2.5-4B@5e10fcc0286756aebf7c41dc52c1e42d95c70281` |
| 权重 | 官方原始 BF16，无量化、无训练 |
| 数据 | `apple/GSM-Symbolic@93b5b3758d9d9841ffe81d6cd2ae2b030685b078`，`test` split |
| 抽样 | 20 个确定性模板键 × `main/p1/p2` = 60 题 |
| 配对 | 每道题各运行一次直接策略和计算器策略，共 120 条轨迹 |
| 主指标 | 严格 numeric pass@1；不可解析、截断和协议失败均计错且不换样 |
| 解码 | thinking off，temperature 0，top_p 1，top_k -1，n=1 |
| 预算 | 每条轨迹累计最多 4096 completion tokens；最多 2 次计算器调用 |
| 统计 | 每 config 精确双侧 McNemar；三次检验做 Holm 校正 |

两臂收到字节完全相同的英文题目，但前置策略不同：一臂要求手算，另一臂要求至少
一次原生函数调用。因此这里估计的是“**策略前缀 + 工具访问**”的联合条件差异，
不是纯粹的工具可用性因果效应。三个 config 共享 `(id, instance)` 模板键，但题面
不同；跨 config 结果只是同模板分层趋势，不能当作同题反事实配对。

完整的预注册选择、prompt、解析器、失败处理和统计口径见
[`PROTOCOL.md`](PROTOCOL.md)。正式生成开始后没有改样本、prompt、工具、参数、
评分器或 120 条分母。

## 结果

### 严格 pass@1

| config | 直接策略 | 计算器策略 | 样本内差值 | McNemar p | Holm p |
|---|---:|---:|---:|---:|---:|
| `main` | 17/20 = 85% | 13/20 = 65% | -20 pp | 0.12500 | 0.37500 |
| `p1` | 16/20 = 80% | 12/20 = 60% | -20 pp | 0.21875 | 0.43750 |
| `p2` | 12/20 = 60% | 10/20 = 50% | -10 pp | 0.68750 | 0.68750 |
| 总计（描述性） | 45/60 = 75.00% | 35/60 = 58.33% | -16.67 pp | 不做汇总检验 | 不适用 |

直接策略总体 Wilson 95% 区间为 `[0.6277, 0.8422]`，计算器策略为
`[0.4573, 0.6994]`。汇总区间同样仅作描述，因为三档复用了模板块。配对转移为：
32 题两臂都对、12 题两臂都错、13 题仅直接策略答对、3 题仅计算器策略答对。

### 把“工具成功”与“任务成功”分开

| 计算器策略中的实际调用数 | 轨迹数 | 严格正确 | 可解析末答 |
|---:|---:|---:|---:|
| 0 | 20 | 16 | 17 |
| 1 | 17 | 14 | 16 |
| 2 | 23 | 5 | 5 |

这是后验描述，不能把调用次数和正确率解释成因果关系。但它清楚定位了接口失配：

- 直接策略可解析 55/60，计算器策略可解析 38/60；
- 全部 27 条不可解析记录都能解释为 9 条 4096-token 截断，加上 18 条两次调用后
  仍输出文字化第三次调用；
- 13 个“仅直接策略答对”中，有 12 个对应上述第三次调用交付失败，另 1 个是模型
  未调用工具并被长度截断；
- 3 个“仅计算器策略答对”中，2 个发生了真实工具调用，1 个没有调用，所以只能
  归因于完整策略条件，而不能都说成“计算器救回”。

63/63 次 `executor_successful_calls` 只说明算术表达式被白名单执行器正确求值，不
说明表达式对题意建模正确。例如 `p1-id24-i08` 把运动消耗的 100 卡路里写成减法，
计算器精确执行了错误方程，仍然得到错误答案。

### 推理完整性审阅

冻结规则选中了 75/120 条轨迹、覆盖 45 道题：全部 40 条错误/不可解析轨迹、全部
40 条实际工具调用轨迹、16 组 A/B 分歧的两臂，以及每个 config 预选的一题两臂。
主标签统计如下：

| 标签 | 数量 |
|---|---:|
| coherent | 32 |
| tool protocol | 18 |
| truncation | 9 |
| semantic/planning | 7 |
| relevant-clause omission | 4 |
| dataset ambiguity | 4 |
| arithmetic | 1 |

审阅发现 1 条严格意义的 right-answer/wrong-reasoning：`p2-id26-i27` 的直接策略
末答为正确的 1680，但可见推导同时保留了“连续减少 20% 和 50% 等于总计减少
70%”的错误等式。另有多条 false start 被模型明确纠正，只标记 `self_corrected`，
不硬凑 RWRA。GSM-Symbolic 的 rationale 不作为权威证明；审阅按题面独立核算，
并如实保留了 4 条涉及题面/金标解释歧义的轨迹（对应 3 道题）。

逐条标签和具体证据见 [`reasoning/review.jsonl`](reasoning/review.jsonl)，七组未经
改写的完整代表轨迹见 [`reasoning/cases.md`](reasoning/cases.md)。审阅由 Codex
多代理辅助逐条完成，确定性事实由脚本重算和校验；提交者对最终材料负责。

## 与其他 Issue / Discussion 投稿相比的互补优势

截至提交前，我复核了[赛题 Issue #9](https://github.com/XHToken/Spark-X2.5/issues/9)
及其公开投稿。已有案例很好地覆盖了 thinking 开关、中英文提示、常规数值扰动、
标准数学集，也已有受限计算器条件。本案例不以贬低或复刻这些方向为目标，而是在
以下组合上提供互补证据：

1. 使用 **4B 原始 BF16**，在 GSM-Symbolic `main/p1/p2` 上做模板键配平，而不是
   只展示若干成功题或单一平均分；
2. 对完全相同题面做直接策略/原生函数调用策略 A/B，公开每一轮 function call、
   参数、执行器返回和终局输出；
3. 把模型的工具采纳、执行器成功、语义建模、调用上限和末答交付分别计量，不把
   “工具执行成功”等同于“推理正确”，也不把联合条件误写成纯工具因果；
4. 先冻结协议再生成，保留 120 条原始轨迹、失败样本、历次合成 pilot、配对检验
   与 Holm 校正，并对冻结选集中的 75 条轨迹做带具体证据的推理审阅。

因此，本案例的优势不是宣称更高的 benchmark 分数，而是给出一个可证伪、可复算、
包含负结果的 Agent 工具使用闭环，并把失败落到可以继续改进的接口层。

## 运行资源、成本与限制

| 项目 | 直接策略 | 计算器策略 |
|---|---:|---:|
| prompt tokens（各 API turn 求和） | 12,464 | 66,446 |
| completion tokens | 39,980 | 41,150 |
| total API tokens | 52,444 | 107,596 |
| 单轨迹时长中位数 | 2.317 s | 3.372 s |

正式窗口从 `2026-09-13T08:14:05Z` 到 `08:16:56Z`，端到端 171.509 秒，使用
4 个并发 worker。时长只作描述：机器为共享 GPU 服务器，不能据此声称吞吐优势。
本次复用现有 A800-SXM4-80GB 和本地权重，增量费用为 0；整机历史成本未知。

这 20 个模板是审计样本，不是官方排行榜估计。greedy decoding 是减少 A/B 方差的
控制选择，而不是追求最高单次分数的设置。
数值替换降低逐字答案记忆风险，却不能排除模板污染。两次工具调用上限是本协议的
部署约束；增加上限或改成强制 `tool_choice` 可能改变结果，但本次没有事后补跑。

## 证据索引

| 证据 | 内容 |
|---|---|
| [`results/summary.json`](results/summary.json) | 全部指标、区间、配对表、调用与资源统计 |
| [`results/per_item.jsonl`](results/per_item.jsonl) | 120 条逐项严格评分和 raw SHA256 |
| [`runs/raw.jsonl`](runs/raw.jsonl) | 120 条完整模型响应、工具调用、返回和 token 记录 |
| [`runs/run.log`](runs/run.log) | 正式运行起止和 120 个任务状态，0 次基础设施重试 |
| [`reasoning/review.jsonl`](reasoning/review.jsonl) | 75 条推理完整性审阅 |
| [`reasoning/cases.md`](reasoning/cases.md) | 七组可直接阅读的双臂完整轨迹 |
| [`evidence/environment.json`](evidence/environment.json) | 模型/数据 revision、权重 LFS SHA256、硬件和镜像 digest |
| [`evidence/runtime/vllm-startup.sanitized.log`](evidence/runtime/vllm-startup.sanitized.log) | 脱敏启动、权重加载、服务就绪日志 |
| `evidence/pilot*` | 不与正式样本重叠的失败 pilot、接口校准及最终通过 gate |
| [`SHA256SUMS`](SHA256SUMS) | 所有公开证据文件的完整性清单 |

## 复现

### 1. 固定源码、数据和模型

```bash
git clone https://huggingface.co/datasets/apple/GSM-Symbolic cache/GSM-Symbolic
git -C cache/GSM-Symbolic checkout 93b5b3758d9d9841ffe81d6cd2ae2b030685b078

hf download XHToken/Spark-X2.5-4B \
  --revision 5e10fcc0286756aebf7c41dc52c1e42d95c70281 \
  --local-dir models/Spark-X2.5-4B

git clone https://github.com/XHToken/Spark-plugin.git cache/Spark-plugin
git -C cache/Spark-plugin checkout ddef50f6f1eda417b6716b27e0aa35d4a6cd0cf3
python -m pip wheel --no-deps cache/Spark-plugin -w dist
```

本次运行的五个权重 LFS SHA256 和数据源文件 SHA256 均在
[`evidence/environment.json`](evidence/environment.json) 中。请先选择空闲 GPU；下面
的 `device=0` 只是复现示例。

### 2. 启动与本次一致的 vLLM 服务

```bash
docker run --rm --name spark-x25-repro \
  --gpus '"device=0"' \
  -p 127.0.0.1:50269:30000 \
  -v "$PWD/models/Spark-X2.5-4B:/model:ro" \
  -v "$PWD/dist:/wheels:ro" \
  --entrypoint bash \
  vllm/vllm-openai:v0.23.0@sha256:6d8429e38e3747723ca07ee1b17972e09bb9c51c4032b266f24fb1cc3b22ed8f \
  -lc 'python3 -m pip install --no-deps /wheels/*.whl && \
    VLLM_PLUGINS=spark2_5 SPARK2_5_PLUGIN_OVERRIDE=1 exec vllm serve /model \
    --host 0.0.0.0 --port 30000 --trust-remote-code \
    --served-model-name spark-x2.5-4b --chat-template /model/chat_template.jinja \
    --enable-auto-tool-choice --tool-call-parser spark25 --dtype bfloat16 \
    --tensor-parallel-size 1 --gpu-memory-utilization 0.25 --max-model-len 32768'
```

宿主仅暴露 `127.0.0.1:50269`。本次实际环境是 A800-SXM4-80GB、TP=1、
vLLM 0.23.0；没有训练、量化或上传权重。

### 3. 生成选择清单并运行

```bash
uv sync --all-extras --locked
uv run python scripts/prepare_selection.py --dataset-root cache/GSM-Symbolic

uv run python scripts/run_pilot.py \
  --base-url http://127.0.0.1:50269/v1 \
  --model spark-x2.5-4b \
  --protocol-commit cdfe83a112308380c6a4bae5adb9de14f38c7bc2 \
  --runtime-json evidence/environment.json \
  --output-dir evidence/pilot-v5

uv run python scripts/run_evaluation.py \
  --base-url http://127.0.0.1:50269/v1 \
  --model spark-x2.5-4b \
  --manifest data/selection_manifest.jsonl \
  --excerpt third_party/gsm_symbolic_selected.jsonl \
  --runtime-json evidence/environment.json \
  --protocol-commit cdfe83a112308380c6a4bae5adb9de14f38c7bc2 \
  --output-dir runs/live --log runs/run.log --workers 4
```

固定 seed 和 greedy decoding 降低随机性，但并行调度、GPU kernel 与运行时差异意味着
不承诺跨硬件 bit-identical generation。公开仓库已经保留本次实际 raw outputs，
复算统计不需要 GPU。

### 4. 离线复算和验收

```bash
uv run python scripts/summarize.py
uv run python scripts/audit_reasoning.py
uv run python scripts/render_cases.py
uv run python scripts/update_checksums.py
uv run python scripts/verify_artifacts.py
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

`verify_artifacts.py` 会从 raw 重新评分，重放 63 次白名单算术调用，重建推理审阅，
核对 SHA256，并阻止 secret、个人路径和模型权重进入公开仓库。

## 许可与责任

原创代码按 [Apache-2.0](LICENSE) 发布。必要的 Apple GSM-Symbolic 原文摘录保持
未修改，仍受 CC BY-NC-ND 4.0 约束，不受本仓库 Apache-2.0 许可覆盖；详见
[`THIRD_PARTY.md`](THIRD_PARTY.md)。本仓库不包含模型权重。

本实验使用 AI 辅助代码实现、审阅和材料整理。模型输出只作为待评分、待核验的实验
数据，不作为未经验证的事实；提交者已理解实验限制并对公开材料负责。
