# Agent Safety Capstone：单人、一个 Quarter、有限算力的选题审计

更新日期：2026-09-29  
主要资料源：[CryptoAILab/Awesome-LM-SSP](https://github.com/CryptoAILab/Awesome-LM-SSP)

## 先给结论

我最建议讨论的题目是：

> **Can Agent-Safety Benchmarks Be Solved Without Reading the Trajectory? A Partial-View and Group-Split Audit of Compact Safety Judges**  
> **不读完整轨迹也能做对吗？小型 Agent Safety Judge 的局部视图与分组切分审计**

它问的不是“再训练一个 guard”，而是一个更基础、算力更低的问题：**现有 agent-safety benchmark 的标签究竟需要理解多步轨迹，还是从用户请求、工具名、最终回答等表面线索就能猜出来？**

最小版本只需要一个公开数据集、一个 CPU 线性分类器和一个冻结的 0.6B–4B 小模型。没有训练大模型、没有真实浏览器或 MCP 环境，也不需要生成新的攻击。即使结果是“局部视图完全不够”，这仍然是有价值的结论：它说明该 benchmark 确实在测多步轨迹理解。

我建议带给导师的优先级是：

1. **局部视图与分组切分审计**：最省算力、研究问题最清楚。
2. **无损轨迹格式分歧能否发现 judge 错误**：与 JAILJUDGE 最直接，实验稍多。
3. **检索式 safety judge 的收益能否跨任务泛化**：数据和方法现成，工程量中等。
4. **有限上下文下的当前授权状态审计**：演示效果好，但与最新论文重叠较多，适合做复现扩展。

## 我实际检查了什么

这份仓库本质上是一个大型文献目录，并不包含所有论文正文。仓库快照为 commit `fe3afa0f06749cb42f11236ce4ebe12449d1a0c8`，提交日期为 2026-09-02。

- 检查了仓库全部 **38 个 tracked files**，包括 README、book/competition/leaderboard/survey/toolkit 汇总、Safety/Security/Privacy 分类清单、LICENSE 和图片。
- README 宣称共收录 **2,467 篇论文**，其中 Agent 类 162 篇；逐行解析实际得到 **2,555 个带日期的论文条目**。差异来自计数没有同步更新、跨类别重复和少量异常文件，不能把 README 数字当作精确去重后的论文数。
- 对全部条目做了标题、日期、类别和链接层面的目录审计；发现 27 组重复标题、31 组重复 URL，以及同一工作跨多个类别重复出现的情况。
- 对 `security/agent.md` 的 **162/162 篇论文逐篇核对 primary-source metadata 与 abstract**；进一步精读了与可落地选题最相关的方法、实验、限制和资源。
- 又检查了仓库快照之后或未被正确归类、但会直接影响新颖性的近期工作，包括 benchmark validity、judge invariance、上下文压缩、授权记忆、人工升级和小型 step guard。

因此，这里的“仔细研读”是：**全部仓库文件与目录条目审计 + 全部 162 篇 agent-security 条目的主源摘要核验 + 核心论文全文重点阅读**。不能诚实地说在一个会话里全文读完了目录中的两千多篇论文；其中大量内容也不属于 agent safety。

仓库还有几个使用时必须注意的问题：

- `security/agent.md` 从 2025-02 开始，早期基础工作被散落在其他文件。例如 [AgentDojo](https://arxiv.org/abs/2406.13352) 和 [InjecAgent](https://arxiv.org/abs/2403.02691) 在 prompt-injection 分类，[Agent Security Bench](https://arxiv.org/abs/2410.02644) 在 general security 分类。
- 同一论文可能因标题修订而在清单中使用旧标题；“收录月份”也不一定是当前 arXiv 版本日期。
- 该仓库适合做 discovery，不适合直接证明一个选题“没人做过”。新颖性必须另外检索最新主源。

## 这批文献形成的研究地图

### 1. 攻击面已经从输入文本扩展到整个 agent 系统

研究对象包括间接 prompt injection、工具描述与工具返回污染、MCP server/tool supply chain、memory poisoning、跨 agent 通信、GUI/网页内容和持久化 skill。通用版“给工具描述加恶意提示，再看 agent 会不会中招”已经非常拥挤。

代表资源包括 [AgentDojo](https://arxiv.org/abs/2406.13352)、[InjecAgent](https://arxiv.org/abs/2403.02691)、[MCPSecBench](https://arxiv.org/abs/2508.13220) 和 [MCP Safety Training](https://arxiv.org/abs/2505.23634)。

### 2. 安全目标正在从 harmful text 转向“这一步是否被授权”

Agent 的回答本身可能无害，但它调用了错误账户、把数据发给了错误对象、沿用了已经撤销的权限，或者把工具内容当成用户授权。这里需要判断的是 **actor、source、scope、time 与 action** 的组合，而不是单句是否有毒。

[Progent](https://arxiv.org/abs/2504.11703)、[MiniScope](https://arxiv.org/abs/2512.11147)、[StepGuard](https://arxiv.org/abs/2608.24777) 和 [Endogenous Authorization Laundering / EAL-Bench](https://arxiv.org/abs/2609.01836) 已覆盖相当多的权限与运行时控制问题。

### 3. “评估 agent”与“评估 safety judge”是两个不同问题

[Agent-SafetyBench](https://arxiv.org/abs/2412.14470)、[AgentDojo](https://arxiv.org/abs/2406.13352) 等主要测 agent 在环境里是否安全完成任务；[R-Judge](https://arxiv.org/abs/2401.10019)、[AgentAuditor/ASSEBench](https://arxiv.org/abs/2506.00641)、[ATBench](https://arxiv.org/abs/2604.02022) 则让 judge 阅读已有轨迹并判断风险。Solo + Colab 最适合后者，因为可以复用静态日志，不必重跑昂贵环境。

### 4. 新问题越来越集中在评测是否可信

近期工作已经指出：类别比例会改变 F1 和模型排名；等价 rubric 改写会翻转 judge 判定；轨迹结构解析能力会限制 guard；人工监督的预算本身也是有限资源。相关工作包括 [Safety, or Just Capability?](https://arxiv.org/abs/2607.28685)、[Policy Invariance](https://arxiv.org/abs/2605.06161) 和 [TraceSafe](https://arxiv.org/abs/2604.07223)。

这与 Zhao Xu 的 [JAILJUDGE](https://arxiv.org/abs/2410.12855) 很契合：研究重点仍然是“安全 judge 的结果什么时候可信”，只是对象从单轮 jailbreak 回答扩展为多步 agent trajectory。

## 题目 1：局部视图与分组切分审计（首选）

### 研究问题

1. 只看用户请求、工具名/工具 schema、动作序列或最终回答，能否接近读取完整 trajectory 的安全判定效果？
2. 随机切分下的高分，在按任务、工具或模板分组后是否仍然存在？
3. 哪些风险类别真的需要跨步骤证据，哪些类别主要依赖词汇捷径？

### 最小实验

- 主数据：[ATBench](https://arxiv.org/abs/2604.02022) 的 1,000 条人工审计轨迹；先做 500 条 pilot 即可。它包含 503 条 safe、497 条 unsafe，平均约 9 步，并带风险来源、失败模式和理由。
- 可选外部验证：[R-Judge](https://arxiv.org/abs/2401.10019) 的 569 条多轮记录。
- 为每条样本自动生成五个视图：full trajectory、user-only、tool/schema-only、action-only、final-answer-only。
- 两种模型：TF-IDF + logistic regression（CPU）和一个冻结的小 guard。小模型可先用 [Qwen3Guard-Gen-0.6B](https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B)，资源允许时再加 [StepGuard-4B](https://huggingface.co/ninty-seven/StepGuard)。
- 两种切分：普通随机切分；按 task/tool/template cluster 的 group-held-out 切分。同一基础任务的改写必须留在同一侧。

### 指标与可交付成果

- Macro-F1、AUROC、unsafe false-negative rate、safe false-positive rate。
- `partial-view score / full-view score`，以及 random split 到 group split 的性能下降。
- 每个风险类别的 bootstrap confidence interval。
- 人工分析 80–100 个典型错误，区分 lexical shortcut、缺少跨步证据和结构解析失败。
- 最终产物：一个可复用的 benchmark-audit 脚本、一张“哪些标签必须读轨迹”的证据地图，以及简单网页/Notebook 演示。

### 新颖性边界

不能声称首次审计 agent-safety benchmark；[Safety, or Just Capability?](https://arxiv.org/abs/2607.28685) 已审计 base rate、指标和构念效度，[TraceSafe](https://arxiv.org/abs/2604.07223) 已研究结构能力。这里的具体贡献应写成：

> **在任务/工具分组 held-out 条件下，系统测量各类局部信息对安全标签的充分性，从而识别 benchmark shortcut。**

这不是训练新 detector。局部视图表现高说明 benchmark 可能存在 shortcut；表现低则为完整轨迹评估的必要性提供证据。两种结果都成立。

### 工作量与风险

算力最低。大部分数据变换、线性基线和统计分析可在 CPU 完成；小模型仅做推理。主要风险是 cluster 定义主观，因此要同时报告 exact group、embedding cluster，并人工核验一小批分组。

## 题目 2：无损轨迹格式分歧能否发现小型 judge 的错误

### 研究问题

同一条轨迹在事实、角色和事件顺序完全不变时，仅改变序列化格式，judge 的判定是否会变化？这种分歧能否在固定复核预算下，比置信度或重复采样更有效地找到误判？

### 最小实验

- 从 ATBench 或 ASSEBench 取 400–600 条测试轨迹。
- 用可逆程序生成三种表示：canonical JSON、带 role/source 的事件表、role-block plain text。
- 做 round-trip test，保证字段、角色、事件顺序和文本内容均可恢复；自由摘要、删 CoT 或改写不算“无损”。
- 每条样本固定三次模型调用，比较：
  1. 三种格式的 disagreement；
  2. 同一格式三次采样的 disagreement；
  3. 单次模型置信度；
  4. 随机送审。
- 在 calibration split 选择送审阈值，在 untouched group-held-out test 上报告结果。

### 指标与产物

- 误判检测 AUPRC/AUROC、risk–coverage 曲线、固定 10%/20% 人工复核比例下的 unsafe 漏检率。
- token、延迟和调用次数必须匹配；不能用更多计算假装方法更好。
- 产物是一个“通过／拦截／待复核”的小 demo，很适合在 capstone 展示。

### 新颖性边界

[Policy Invariance](https://arxiv.org/abs/2605.06161) 已证明等价 rubric 改写会翻转判定，也提出按改写敏感度做弃权的方向；公开的自动研究报告 [View-Disagreement Escalation](https://lemma-public-asset.analemma.ai/online/fars/live/live_live_20260213/idea_ed555e4e-a31d-4e17-a0ef-e1ba09213e4f/main.pdf) 已尝试用不同视图分歧升级，但使用的是 70B judge、任务成功标签和非等价视图。这个项目只能定位为：**小型 agent-safety guard、严格无损表示、相同计算预算下的受控实证**。它是增量研究，但和 JAILJUDGE 的 judge reliability 主题最接近。

## 题目 3：检索式 safety judge 的收益能否跨原始任务泛化

### 研究问题

给 safety judge 检索几个相似的历史案例后，准确率可能提高；但提升究竟来自可迁移的风险模式，还是 memory 里出现了同一任务或近重复模板？

### 最小实验

- 使用 [ASSEBench/AgentAuditor](https://github.com/Astarojth/AgentAuditor-ASSEBench) 的 1,476 条 safety 轨迹；若推理慢，固定抽取约 600 条。
- 本次数据检查发现：1,476 条中有 1,307 个不同的首条 user 文本；34 个 exact-query 重复组覆盖 203 条，最大组有 28 条。这只说明需要控制相关性，**不是对原论文的数据泄漏指控**。
- 比较 direct judge、random 3-shot、embedding-retrieved 3-shot；统一示例数与 token budget。
- 比较 random split、exact-query group split、semantic-near-duplicate group split、scenario holdout。
- 固定一个本地 3B–4B judge 即可；无需训练，只建立检索索引并推理。

### 指标与产物

- Macro-F1、unsafe FNR、每个 split 的 retrieval gain、检索近邻相似度与正确率关系。
- 对 50–100 个 semantic cluster 人工核验，防止错误合并。
- 发布 clean grouped splits 和可复现实验脚本。

### 新颖性边界

[AgentAuditor](https://arxiv.org/abs/2506.00641) 已研究聚类、标签噪声、memory poisoning 和跨数据集迁移。因此贡献不是“发明 RAG safety judge”，而是：**将同一数据源内部的近重复记忆收益与跨任务风险识别分开测量**。如果不同 split 差异很小，结论同样有用：它说明检索增益并非主要依赖模板重复。

## 题目 4：有限上下文下，小型 guard 能否判断“当前”授权状态

### 研究问题

在 grant、revoke、expiry 和不同信息来源混合的长历史中，固定小 guard 会不会继续沿用已撤销的旧授权？普通摘要、逐字保留规则和结构化 authorization ledger 分别会带来多少漏放与误拒？

### 最小实验

- 只做 email 与 file-sharing 两个 mock domain。
- 120 对样本，最多扩到 200 对；每对最终工具调用完全相同，只改变授权事实：授予/未授予、撤销/未撤销、用户授予/工具内容自称授予、有效/过期。
- 比较 full history、last-k、普通摘要、verbatim pinning、oracle ledger、模型自动抽取 ledger；所有压缩条件使用同样 token budget。
- 主实验是静态 action review；只做 20–30 个可执行 Python mock 作为演示。
- 用 StepGuard-4B 加一个通用 3B–4B 模型，冻结推理，不重训。

### 指标与产物

- Unauthorized allow、authorized false refusal、paired consistency、stale-grant retention、token、延迟。
- 把 oracle ledger 与自动 ledger 分开，才能区分“状态表示失败”和“judge 判断失败”。

### 新颖性边界

这个方向最拥挤。[Governance Decay](https://arxiv.org/abs/2606.22528)、[Compaction Cliff](https://arxiv.org/abs/2608.22752)、[GateMem](https://arxiv.org/abs/2606.18829) 和尤其新的 [EAL-Bench](https://arxiv.org/abs/2609.01836) 已覆盖约束遗失、权限更新、撤销、来源洗白、event sourcing 与误拒权衡。因此它适合被描述为：

> **对现有 memory-governance 结论在小型、有限上下文 step guard 上的受控复现和错误分解。**

它的工程 demo 最直观，但如果导师要求明显的论文新颖性，我会优先选择题目 1 或 2。

## 不建议作为主项目的方向

| 想法 | 原因 |
|---|---|
| 从头训练 StepGuard 或新的 agent guard | StepGuard 原训练使用 4×H200；不符合 Colab 约束。冻结推理可行。 |
| 搭完整 browser/GUI/MCP red-team 环境 | 环境、API、外部服务和安全隔离工作会吃掉 quarter，研究问题反而被工程淹没。 |
| “上下文压缩会不会丢安全规则” | Governance Decay、Compaction Cliff、TRACE、GateMem、EAL-Bench 已直接覆盖通用版本。 |
| “危险工具名会不会导致误拒” | [CautiousBench](https://arxiv.org/abs/2608.27009) 已用 benign/unsafe twins 系统研究。 |
| “低置信度时交给人工” | 一般性的 selective prediction、review budget 与 escalation 已有大量工作；必须加入 agent trajectory 特有且严格受控的新变量。 |
| 再做一个工具描述 prompt injection 攻击 | Tool Preferences、ToolHijacker、MPMA、LLMCert-T 等已非常接近，且容易沦为换模型复现。 |
| 同时做量化、跨语言、RAG、压缩和 agent safety | 每一项都会增加解释变量。一个 quarter 应只保留一个主问题。 |

## 首选题目的 10 周执行计划

| 周 | 工作 |
|---|---|
| 1 | 下载 ATBench，复现官方 schema 和标签统计；用 30–50 条测试小模型吞吐与输出解析。 |
| 2 | 定义五种 information views；实现严格的数据校验和去重报告。 |
| 3 | 建立 random、exact-group 和 task/tool-cluster splits；人工核验 50 个 cluster。 |
| 4 | 跑 TF-IDF/logistic regression 与简单词汇/长度基线。 |
| 5 | 跑 0.6B 冻结 guard；根据 Colab 吞吐决定是否加入 4B 模型。 |
| 6 | 完成 full/partial views × splits 主矩阵，缓存所有原始输出。 |
| 7 | 做 bootstrap、类别分层和 paired significance analysis。 |
| 8 | 人工审计 80–100 个错误，形成 shortcut 与 evidence-failure taxonomy。 |
| 9 | 完成 Notebook/小 demo、图表和复现说明。 |
| 10 | 写报告、整理 presentation，并只补最能回答导师问题的一项消融。 |

明确的 scope cut：如果第 1 周 4B 推理太慢，就只保留 0.6B guard；如果 cluster 质量不好，就用 exact task/tool group，不追加复杂聚类模型；R-Judge 只作为有余力时的外部验证。

## 可以直接对导师说的英文 pitch

> I want to study whether current agent-safety benchmarks actually require a judge to understand the full multi-step trajectory. Using ATBench, I will compare full trajectories with user-only, tool-only, action-only, and final-answer-only views under both random and task/tool-grouped splits. The project uses a CPU lexical baseline and one frozen compact safety model, so it requires no agent rollout or model training. The main deliverable is a benchmark audit showing which risk categories contain shortcuts and which truly require cross-step evidence. This extends safety-judge evaluation, which aligns closely with JAILJUDGE, from single responses to tool-using agent trajectories.

建议在会面时问三件事：

1. 他更希望 capstone 的贡献是 **benchmark/evaluation audit**，还是必须包含一个新的 defense system？
2. 他是否有内部的 JAILJUDGE guard、agent trajectory 或 API credits 可以作为第二模型/外部数据？没有也不影响最小项目。
3. 对一个 quarter 的项目，他是否接受“严谨的 negative result”，例如局部视图没有 shortcut，或格式分歧不优于置信度？

## 核心资源

- 总目录：[Awesome-LM-SSP](https://github.com/CryptoAILab/Awesome-LM-SSP)
- 领域综述：[Trustworthy LLM Agents](https://arxiv.org/abs/2503.09648)
- Agent 评测：[Agent-SafetyBench](https://arxiv.org/abs/2412.14470)、[AgentDojo](https://arxiv.org/abs/2406.13352)、[Agent Security Bench](https://arxiv.org/abs/2410.02644)
- Judge 数据：[R-Judge](https://arxiv.org/abs/2401.10019)、[ASSEBench](https://arxiv.org/abs/2506.00641)、[ATBench](https://arxiv.org/abs/2604.02022)
- 小型 guard：[Qwen3Guard-Gen-0.6B](https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B)、[StepGuard](https://arxiv.org/abs/2608.24777)
- 评测可信度：[Policy Invariance](https://arxiv.org/abs/2605.06161)、[Safety, or Just Capability?](https://arxiv.org/abs/2607.28685)、[TraceSafe](https://arxiv.org/abs/2604.07223)
- 与 Zhao Xu 的直接连接：[JAILJUDGE](https://arxiv.org/abs/2410.12855)

## 逐篇核验附录

162 篇 `security/agent.md` 条目的逐篇记录按清单月份拆成三份；每份都注明了阅读深度，避免把摘要核验写成全文精读：

- [2025/02–06：67 篇](./audit/agent_2025_feb_jun.md)
- [2025/07–10：59 篇](./audit/agent_2025_jul_oct.md)
- [2025/11–2026/08：36 篇](./audit/agent_2025_nov_2026_aug.md)
