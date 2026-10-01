# Agent 安全文献核验：2025/02–06

核验日期：2026-09-29。来源清单：`tmp/Awesome-LM-SSP/collection/paper/security/agent.md`。

本文件覆盖该清单中 2025/02–06 全部 67 篇条目。每篇均核对 primary-source metadata 和 abstract；另重点阅读 AgentAuditor、Tool Preferences、Progent、RealHarm、MCP Safety Training 的方法、实验、限制及相关附录，检查公开资源及近期重叠。本文件不是“67 篇全部全文精读”的声明，也未运行模型或复现实验。

月份沿用原清单分组；核验取访问时可得的最新 arXiv 版本，不能将分组月份当作所读版本的发布日期。研究建议针对 solo、10-week、Colab、优先离线小模型推理的 capstone。

## 1. 覆盖与分类计数

T=threat，E=evaluation，D=defense，S=system/survey。每篇按主要贡献单标签计数；这不排除次要贡献。

| 月份 | T | E | D | S | 合计 |
|---|---:|---:|---:|---:|---:|
| 2025/02 | 1 | 1 | 0 | 0 | 2 |
| 2025/03 | 2 | 1 | 2 | 2 | 7 |
| 2025/04 | 4 | 5 | 6 | 3 | 18 |
| 2025/05 | 7 | 6 | 5 | 2 | 20 |
| 2025/06 | 5 | 8 | 2 | 5 | 20 |
| **总计** | **19** | **21** | **15** | **12** | **67** |

- 67/67 primary metadata＋abstract 可访问，没有摘要级缺项。
- RealHarm 的 arXiv HTML 访问失败，改用 [ACL 正式论文及 PDF](https://aclanthology.org/2025.llmsec-1.7/) 阅读。
- MCP-FBAs 的代码可读，作者 README 明确说明 HF 数据 gated；未取得 gated 数据，不能声称开箱即用。
- 标题版本变化包括 AgentXploit→AgentVigil、Gaming Tool Preferences→Tool Preferences in Agentic LLMs Are Unreliable、Disclosure Audits→Beyond Jailbreaking: Auditing Contextual Privacy、Screen Hijack→Poison Once, Control Anywhere、Get Agents Drunk→DrunkAgent。
- Progent v3 已加入 SMT 判断权限更新的收缩/扩张，不能只按 2025 初稿判断创新性。
- 本次抓取的原始证据暂存在 `/tmp/agent_febjun2025.json`、`/tmp/agent_febjun2025_abstracts.json`、`/tmp/agent_febjun2025_classified.json`；临时文件不是持久归档保证。

## 2. 逐篇核验表

每行均已核对 primary metadata＋abstract；★ 表示进一步读正文方法、实验、限制和资源。标题使用便于辨认的简称，链接定位原文。

| 月 | 论文 / primary URL | 类 | 核心位置 |
|---|---|---|---|
| 06 | [Corrupted by Reasoning](https://arxiv.org/abs/2506.23276) | E | 公共品博弈、推理模型搭便车 |
| 06 | [Agent-to-Agent Theory of Mind](https://arxiv.org/abs/2506.22957) | E | 对话对象识别、模型间社会推理 |
| 06 | [★ AgentAuditor](https://arxiv.org/abs/2506.00641) | E | 轨迹安全 judge、ASSEBench、检索推理记忆 |
| 06 | [From Prompt Injections to Protocol Exploits](https://arxiv.org/abs/2506.23260) | S | agent workflow/protocol 威胁整理 |
| 06 | [MCPCorpus](https://arxiv.org/abs/2506.23474) | E | MCP server/client 生态数据资源 |
| 06 | [SHADE-Arena](https://arxiv.org/abs/2506.15740) | E | 隐藏破坏目标、监控器有效性 |
| 06 | [Survey of LLM-Driven Agent Communication](https://arxiv.org/abs/2506.19676) | S | 通信协议、风险、对策 |
| 06 | [Poison Once, Control Anywhere](https://arxiv.org/abs/2506.13205) | T | 原 Screen Hijack；移动 VLM 视觉后门 |
| 06 | [Doppelgänger Method](https://arxiv.org/abs/2506.14539) | T | 角色一致性攻击及对齐训练 |
| 06 | [AGENTSAFE](https://arxiv.org/abs/2506.14697) | E | embodied hazardous instructions；新版摘要称 SAFE |
| 06 | [RAS-Eval](https://arxiv.org/abs/2506.15253) | E | CWE 导向的 agent 安全测试 |
| 06 | [Mind the Web](https://arxiv.org/abs/2506.07153) | T | web-use agent 攻击面 |
| 06 | [Effective Red-Teaming of Policy-Adherent Agents](https://arxiv.org/abs/2506.09600) | T | CRAFT、τ-break、策略相关攻击 |
| 06 | [Beyond Jailbreaking: Auditing Contextual Privacy](https://arxiv.org/abs/2506.10171) | E | 原 Disclosure Audits；上下文隐私审计 |
| 06 | [Specification and Evaluation of Multi-Agent LLM Systems](https://arxiv.org/abs/2506.10467) | S | 多 agent 规范与评估原型 |
| 06 | [COALESCE](https://arxiv.org/abs/2506.01900) | S | agent 任务外包、经济机制 |
| 06 | [ETDI](https://arxiv.org/abs/2506.01333) | D | 工具定义完整性、OAuth/权限机制 |
| 06 | [Beyond the Protocol](https://arxiv.org/abs/2506.02040) | T | MCP 攻击向量 |
| 06 | [To Trust or Not to Trust](https://arxiv.org/abs/2506.02546) | D | 原 Attention Knows Whom to Trust；MAS 信任管理 |
| 06 | [ATAG](https://arxiv.org/abs/2506.02859) | S | agent threat attack graph |
| 05 | [When Ethics and Payoffs Diverge](https://arxiv.org/abs/2505.19212) | E | 社会困境中伦理与收益 |
| 05 | [Revisiting Multi-Agent Debate as Test-Time Scaling](https://arxiv.org/abs/2505.22960) | E | debate 的可靠性和扩展效果 |
| 05 | [MedSentry](https://arxiv.org/abs/2505.20824) | E | 医疗 agent 安全评估及防护 |
| 05 | [RedTeamCUA](https://arxiv.org/abs/2505.21936) | E | GUI/browser agent 端到端攻击基准 |
| 05 | [Seven Security Challenges](https://arxiv.org/abs/2505.23847) | S | agent 安全系统性问题 |
| 05 | [LLM Agents Should Employ Security Principles](https://arxiv.org/abs/2505.24019) | D | AgentSandbox、系统安全原则 |
| 05 | [CoTGuard](https://arxiv.org/abs/2505.19405) | D | 版权风险控制 |
| 05 | [AdInject](https://arxiv.org/abs/2505.21499) | T | agent 中广告投放/行为操纵 |
| 05 | [★ MCP Safety Training](https://arxiv.org/abs/2505.23634) | D | MCP-FBAs、DPO、RAG-Pref |
| 05 | [★ Tool Preferences in Agentic LLMs Are Unreliable](https://arxiv.org/abs/2505.18135) | T | 原 Gaming Tool Preferences；工具描述诱导偏好 |
| 05 | [BountyBench](https://arxiv.org/abs/2505.15216) | E | 网络安全发现/利用/修复能力 |
| 05 | [IP Leakage Attacks Targeting LLM-Based MAS](https://arxiv.org/abs/2505.12442) | T | MASLEAK、多 agent 知识产权泄漏 |
| 05 | [From Assistants to Adversaries](https://arxiv.org/abs/2505.12981) | T | 移动 agent、AgentScan |
| 05 | [Hidden Dangers of Browsing AI Agents](https://arxiv.org/abs/2505.13076) | T | browsing 系统风险 |
| 05 | [Think Twice Before You Act](https://arxiv.org/abs/2505.11063) | D | Thought-Aligner、执行前思维修正 |
| 05 | [MPMA](https://arxiv.org/abs/2505.11154) | T | MCP 工具偏好操纵 |
| 05 | [Proposal for Evaluating Operational Risk of Chatbots](https://arxiv.org/abs/2505.04784) | E | operational-risk 评估设计 |
| 05 | [AgentVigil](https://arxiv.org/abs/2505.05849) | T | 原 AgentXploit；黑盒间接注入搜索 |
| 05 | [LlamaFirewall](https://arxiv.org/abs/2505.03574) | D | 输入检测＋行动对齐检查＋代码扫描 |
| 05 | [Open Challenges in Multi-Agent Security](https://arxiv.org/abs/2505.02077) | S | MAS 安全问题与路线 |
| 04 | [Advances and Challenges in Foundation Agents](https://arxiv.org/abs/2504.01990) | S | foundation agent 综述 |
| 04 | [SAGA](https://arxiv.org/abs/2504.21034) | S | 安全 agent 架构 |
| 04 | [RepliBench](https://arxiv.org/abs/2504.18565) | E | 自主复制能力评估 |
| 04 | [WASP](https://arxiv.org/abs/2504.18575) | E | web agent prompt-injection 基准 |
| 04 | [Prompt Injection Attack to Tool Selection](https://arxiv.org/abs/2504.19793) | T | ToolHijacker、工具检索/选择 |
| 04 | [Securing GenAI MAS Against Tool Squatting](https://arxiv.org/abs/2504.19951) | D | 工具注册与冒名工具 |
| 04 | [Securing Agentic AI: Comprehensive Threat Model](https://arxiv.org/abs/2504.19956) | S | agent 威胁模型 |
| 04 | [Simplified Secure MCP Gateways](https://arxiv.org/abs/2504.19997) | D | MCP gateway 安全架构 |
| 04 | [Human-Centered Evaluation of GUI Agents](https://arxiv.org/abs/2504.17934) | E | GUI 评估方法 |
| 04 | [DoomArena](https://arxiv.org/abs/2504.14064) | E | 模块化 agent 攻防评估环境 |
| 04 | [CheatAgent](https://arxiv.org/abs/2504.13192) | T | 推荐 agent 攻击 |
| 04 | [MCP Guardian](https://arxiv.org/abs/2504.12757) | D | MCP 控制/防护 |
| 04 | [★ Progent](https://arxiv.org/abs/2504.11703) | D | 工具参数级权限策略 |
| 04 | [The Obvious Invisible Threat](https://arxiv.org/abs/2504.11281) | T | GUI 细小文字注入 |
| 04 | [★ RealHarm](https://arxiv.org/abs/2504.10277) | E | 真实已报道事故、moderation 缺口 |
| 04 | [Enterprise-Grade Security for MCP](https://arxiv.org/abs/2504.08623) | D | 企业 MCP 安全 |
| 04 | [Detecting Malicious AI Agents Through Simulated Interactions](https://arxiv.org/abs/2504.03726) | D | 交互式恶意 agent 检测 |
| 04 | [MCP Safety Audit](https://arxiv.org/abs/2504.03767) | T | MCP falsely-benign exploit 与 scanner |
| 03 | [Survey on Trustworthy LLM Agents](https://arxiv.org/abs/2503.09648) | S | trustworthy agent 综述 |
| 03 | [AgentDAM](https://arxiv.org/abs/2503.09780) | E | web agent 数据最小化 |
| 03 | [MCP Landscape, Security Threats, Future Research](https://arxiv.org/abs/2503.23278) | S | MCP 生态综述 |
| 03 | [DrunkAgent](https://arxiv.org/abs/2503.23804) | T | 原 Get Agents Drunk；推荐 agent 记忆污染 |
| 03 | [ShieldAgent](https://arxiv.org/abs/2503.22738) | D | 可验证策略监控、ShieldAgent-Bench |
| 03 | [sudo rm -rf agentic_security](https://arxiv.org/abs/2503.20279) | T | SUDO、上下文/工具攻击 |
| 03 | [Prompt Flow Integrity](https://arxiv.org/abs/2503.15547) | D | prompt/信息流完整性 |
| 02 | [DemonAgent](https://arxiv.org/abs/2502.12575) | T | 后门、混淆与审计规避 |
| 02 | [Nuclear Deployed](https://arxiv.org/abs/2502.11355) | E | 高风险任务中的 agent 决策 |

## 3. 本时段研究地图

1. **攻击面扩展。** 工具选择、工具返回、MCP 配置、记忆与 agent 通信成为主要研究对象。Tool Preferences、MPMA、ToolHijacker 与 MCP 论文集中出现；再找一种工具描述注入已经相当拥挤。
2. **安全目标更依赖任务和授权。** CRAFT、AgentDAM、ShieldAgent、Progent 关心“此时、此人、此任务是否允许这一行动”；单独的 harmful-output 分类不足以回答。
3. **agent 和 judge 的评估需区分。** AgentAuditor/R-Judge 衡量读轨迹的判断能力；SHADE、RedTeamCUA、WASP、DoomArena 等衡量执行或监控，不应把离线准确率直接当作端到端防御效果。
4. **防御分为模型侧与执行边界侧。** MCP Safety Training/Thought-Aligner 改变模型判断；Progent/Prompt Flow Integrity 将约束放在程序执行边界。Solo Colab 更适合离线 judge/数据审计，完整 GUI/OS/MCP 攻防系统成本更高。

## 4. 五篇重点阅读结论

### AgentAuditor / ASSEBench

- 方法：提取 scenario/risk/behavior 特征并做 embedding；FINCH 选择代表性案例；结合已知标签生成推理记忆；对待判轨迹检索、重排并进行 few-shot 判断。
- 新版已研究其他聚类方法、标签噪声、三档记忆投毒、跨数据集记忆迁移、检索质量退化。不能把“给 judge 加 RAG”“测记忆投毒”“测 OOD”本身作为新意。
- ASSEBench 的独立轨迹为 817 security＋1,476 safety＝2,293；strict/lenient 是 safety 轨迹的不同标签标准，不能把 5,245 文件行数当成独立样本数。
- [正文与附录](https://arxiv.org/html/2506.00641v3)、[官方代码与数据](https://github.com/Astarojth/AgentAuditor-ASSEBench)。仓库有 Apache-2.0 license；默认代码配置 OpenAI API，纯本地使用需改推理适配层。
- 适合作为数据来源和基线；其多阶段标注/推理成本、标签质量依赖和启发式参数要计入比较。

### Tool Preferences in Agentic LLMs Are Unreliable

- 方法：在 BFCL 单工具问题中添加接口相同、描述编辑的等价工具，双顺序校准位置偏差，比较正确调用与选择比例。
- 已有 17 模型、0.5B–32B 等规模、516/1,316 测例及多种组合编辑；“Qwen 小模型＋描述改写＋选中率”研究性不足。
- 功能等价设计隔离了偏好，但无法直接证明对真实功能正确性的影响；后续可测功能近邻、权限范围等约束，不过近期重叠很多。
- [论文](https://arxiv.org/html/2505.18135v2)、[官方代码数据](https://github.com/kazemf78/llm-unreliable-tool-preferences)。仓库有本地模型后端；无需执行真实工具即可做选择评估。

### Progent

- v3：工具名/参数级符号策略、运行时确定性检查、LLM 初始化/更新策略、SMT 判断权限收缩或扩张，并支持固定高优先级策略与 approval module。
- 不能把 JSON 权限约束、参数级检查、只准自动收缩权限当作新方法。
- 明确边界：权限内的偏好操纵和纯文本最终答案不在其完整保护范围。
- 主要实验使用 GPT-4o；完整复现比离线审计成本高。框架可借作执行边界基线，但小模型适配的有效性需另验。
- [最新正文](https://arxiv.org/html/2504.11703v3)、[官方代码](https://github.com/sunblaze-ucb/progent)。

### RealHarm

- 68 个公开报道事故＋68 个人工修正安全版本。safe/unsafe twins 必须按原事故分组，不能分到训练和测试两侧。
- 已比较内容过滤器与有上下文的 LLM judges；差距并不意味着再加上下文就是新意。
- 优点是现实案例、数据轻；限制是样本量小、公开报道选择偏差、修正文本风格差异。适合作为外部补充测试，不宜独撑主实验。
- [正式论文](https://aclanthology.org/2025.llmsec-1.7/)、[数据](https://huggingface.co/datasets/giskardai/realharm)。

### MCP Safety Training

- RAG-Pref 已经用正/负检索样例做无需训练的偏好对齐，并与 DPO 比较；把检索安全例子当新防御会重叠。
- 核心实验主要是拒绝判定，不能等同真实工具执行安全；合成 CVE→工具调用映射及 benign 样本构造也约束外推。
- 原文实验使用 4×48GB L40S；缩小到本地小模型可以尝试，但不是整套复现适配 Colab 的保证。
- [论文](https://arxiv.org/html/2505.23634v1)、[代码](https://github.com/johnhalloran321/mcp_safety_training)、[数据入口](https://huggingface.co/datasets/johnhalloran/mcp-fbas)。README 说明 gated 数据；仓库当前数据计数与论文版本不同，需固定版本后再实验。

## 5. 近期重叠与不能声称的创新

在这 67 篇中，未发现“等价轨迹表示分歧→选择性 judge 弃权”或“预算约束的授权证据压缩”的完整同构方案。但截至 2026 年，局部空白不能支持全局新颖性声明。

| 拟方向 | 已核实 primary 邻近工作 | 对选题的约束 |
|---|---|---|
| 压缩保安全约束 | [The Compaction Cliff](https://arxiv.org/abs/2608.22752) | 已有逐项类型分类、约束原文保留、来源权重、重复压缩、压缩/检索/分解算子和下游验证；普通 pin 安全规则高度重叠 |
| 长轨迹安全证据压缩 | [DRAFT](https://arxiv.org/abs/2604.03242) | 已有可训练 Extractor→latent draft→Reasoner；不可称首个 evidence compression |
| judge 等价表达不一致 | [Policy Invariance](https://arxiv.org/abs/2605.06161) | 已测等价 rubric 改写、strict/lenient、ambiguity-aware calibration |
| 分歧后弃权/升级 | [Policy Invariance 正文](https://arxiv.org/html/2605.06161v1) | 尚未报告 abstention coverage-risk curves，但 future work 已点名 rubric ensemble 和 rewrite-sensitivity 校准弃权；适合 incremental follow-up |
| 工具偏好简单防御 | [BiasBusters](https://www.microsoft.com/en-us/research/publication/biasbusters-uncovering-and-mitigating-tool-selection-bias-in-large-language-models/) | 已有相关候选过滤后均匀采样 |
| 工具选择稳健性与权限 | [LLMCert-T](https://github.com/uiuc-focal-lab/LLMCert-T) | 已含 intent shift、权限升级、候选淹没、诱导弃权及统计置信界 |
| 缺权限/信息时应停手 | [AgentAbstain](https://arxiv.org/abs/2607.10059) | 已有 paired should-act/should-abstain 及可执行环境；不可称首个授权对照基准 |

其他分工报告的 MRT、TRACE、Analemma/FARS、CautiousBench、Governance Decay、GateMem、SPA、Safe to Resume 也应并入最终重叠矩阵。本文件不将这些团队传回发现伪装成本分工独立完成的全文核验。

## 6. 可落地问题、最小实验和风险

### 题目 1：检索式安全 judge 的收益能否跨原始任务泛化？

**推荐定位：最省事、最稳的离线审计。** 问题是 RAG memory 的增益有多少来自相似任务/模板，有多少在未见任务上仍存在。

实际下载 ASSEBench-safety 后，本次脚本检查发现：1,476 条轨迹包含 1,307 个不同的第一条 user 文本；34 个重复 query 组覆盖 203 条，最大组 28 条。该检查仅比较原始第一条 user 字符串；不是近重复全文分析，也不构成论文数据泄漏指控。

- 最小实验：两个本地 3B/7B judge；direct、random few-shot、embedding retrieval；比较随机划分、query/近重复组划分、scenario holdout。固定 memory 大小、shot 数量和输入 token，按组 bootstrap。
- 新意边界：AgentAuditor 已做跨数据集 OOD；贡献应是同一来源内部的任务相关性与迁移收益拆解，以及可复现 grouped split，不是新 RAG 算法。
- 数据：[ASSEBench](https://github.com/Astarojth/AgentAuditor-ASSEBench)、[R-Judge](https://github.com/Lordog/R-Judge)。不必训练或重新生成 agent 轨迹。
- 风险：泛化差距可能很小，semantic grouping 可能误合并，原数据没有完整 source-task ID。人工复核 50–100 个组，并分别报告 exact-query 与 semantic-group 分析。
- 可交付：clean split、可复现评估脚本、memory 检索可视化、误差分解、统计报告。负结果仍有价值。

### 题目 2：固定算力下，哪一种分歧信号能识别小模型 judge 判错？

**推荐定位：与 JAILJUDGE 衔接更直接的 incremental empirical study。** 将同一轨迹无损表示为原始 chat、明确 role/source 的事件表、canonical JSON，比较表示分歧与普通重复采样的有效性。

- 最小实验：300–500 条按任务分组 held-out 轨迹；1–2 个本地冻结 judge；每例固定三次调用。比较单次置信度、同 prompt 三次采样、三种无损表示。
- 仅在 calibration split 定弃权阈值；测试报告 risk–coverage、unsafe FN、safe FP、token、耗时；对照每种方法相同调用预算。
- 新意边界：分歧升级、ensemble、弃权均有先例；贡献是无损表示与紧凑冻结 judge 的同预算严格对照。必须引用 Policy Invariance 与 Analemma/FARS，不能称首次 disagreement-abstention。
- 风险：三视图可能一致地判错；转换可能改变来源语义；三视图不一定比三次普通采样好。需要可逆转换或字段守恒检查。
- 资源：ASSEBench/R-Judge 静态轨迹即可；无训练、无付费 API；本地适配和上下文长度仍需 pilot。

### 题目 3：压缩历史会不会过度保留已失效的许可？

问题限定为 grant→revoke、授权到期、来源变化时，摘要保住旧 grant 是否造成 unsafe allow，区别于只研究遗漏禁止规则。

- 最小实验：100–150 个具有确切角色、时间、权限状态的 Python mock 任务；每例 allow/deny twins；固定 token 预算，比较尾部截断、普通摘要、规则 pinning、带事件顺序与当前状态的权限记录。
- 新意边界：潜在差异是失效授权残留与过度保留；仍须对照 GateMem、Governance Decay、SPA、Safe to Resume。当前尚不能确认未被覆盖。
- 风险：纯手写权限记录的优势可能只是规则引擎常识。可研究部分应落在自然语言历史到有效授权状态的提取，并分开测提取错误和执行器错误。
- 资源：本地小模型短文本推理＋Python mock，无需真实账号或真实外部系统；比题目 1/2 数据设计负担更大。

### 题目 4：工具描述清洗会不会毁掉区分真实功能的关键条件？

问题是去掉营销/指令句时，防御是否也删去地域、只读/写入、账户范围等合法限制。

- 最小实验：从 BFCL 构造 150–250 组功能近邻；比较原描述、关键词删句、结构化功能字段、相关候选随机选择。测正确工具选择、错误权限选择与 clean utility。
- 新意边界：不能复做描述攻击或完全等价工具实验；需要 BiasBusters、ToolHijacker、LLMCert-T 基线。近期工具权限研究很多，novelty 风险高于题目 1/2。
- 风险：数据过于明显；改写偷偷改变功能；小模型基本调用能力太低。先用 30 例做 pilot，不满足 clean capability 门槛就缩小或换题。

## 7. 算力与十周范围建议

本分工优先推荐题目 2，其次题目 1；题目 3 适合导师确认更窄差异后再定。四个都是待验证的研究问题，未保证方法提升或发表新颖性。

- 主线只选一个，不同时做压缩、防御训练、MCP 系统和新 benchmark。
- 先用 30–50 例验证推理 backend、标签解析、上下文长度与单例耗时，再决定是否可扩大至数百例。Colab 型号和配额不固定，不能预先保证所有 7B 长上下文配置可运行。
- 优先 3B/4B 冻结模型，7B 量化作为第二模型；batch size 1、缓存输出、限制上下文。量化和截断都应记录，不能偷偷改变比较条件。
- 第一阶段完成数据核验、分组和 pilot；中段冻结基线与主实验；后段做误差分析、置信区间、消融和可复现演示。
- 单人标注需保留 rubric、判定证据和歧义标记；若导师/同学可独立复核一小部分，会比扩大未经核验的数据规模更有价值。

