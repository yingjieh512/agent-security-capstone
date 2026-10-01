# Agent safety 文献核验：2025/11–2026/08

核验日期：2026-09-29。来源列表：`tmp/Awesome-LM-SSP/collection/paper/security/agent.md`。

完成分配范围内 **36/36 条 primary-source abstract/metadata 核对**。重点全文阅读 StepGuard、CautiousBench、AgenTRIM、Escalation；SPA、MiniScope、Safe to Resume、SkillShield 等阅读关键方法、实验或局限。另检索到 5 篇与“历史压缩、授权证据与 authorization ledger”直接相邻的论文。没有运行复现实验。

**阅读边界：**“摘要”不代表阅读全文；“关键章节”是选读。资源未核验不等于资源不存在。当前日期为 2026-09-29，因此 2026 年 8 月论文不是未来论文。arXiv 记录能证明公开存在，不能独立证明结论可靠或已经同行评审。文中的可行性和选题评价为分析判断。

## 逐篇核验表

| # | 论文及 primary source | 分类与主要判断 | 阅读/资源状态 |
|---|---|---|---|
| 1 | [Can escalation channels redirect reward hacking toward defect disclosure?](https://arxiv.org/abs/2608.29460) | Reward hacking；给 coding agent 合法缺陷报告渠道 | 全文；代码实际公开 |
| 2 | [Safe to Resume? Breaking Execution Continuity of Agent Execution via Rollback](https://arxiv.org/abs/2608.29381) | 回滚破坏执行连续性；验证、授权、重复提交 | 关键章节；资源未证实 |
| 3 | [Influence Is Not Authority](https://arxiv.org/abs/2608.29942) | 因果影响不代表非法指令；正常工具结果也影响动作 | 摘要；96 条件/24 配对案例 |
| 4 | [SIR: Self-improving Red-teaming for Compute Use Agents](https://arxiv.org/abs/2608.30207) | Computer-use 自适应红队；OS 状态作判据 | 摘要；GUI 环境成本高；标题保留原文 Compute |
| 5 | [Extracting Knowledge from Tools in LLM Agents](https://arxiv.org/abs/2608.30288) | ToolSiphon；通过代理抽取工具后端知识 | 摘要；隐私攻击；资源未核验 |
| 6 | [Attesting Outputs and Delegation Ancestry in Multi-Agent AI Systems](https://arxiv.org/abs/2608.30387) | 输出签名与委托 DAG；可验证来源 | 摘要；不是 prompt injection 防御保证 |
| 7 | [ECLIPSE](https://arxiv.org/abs/2608.30441) | 长链隐蔽注入、迭代攻击 | 摘要；同时操控用户请求和工具内容，须说明威胁模型 |
| 8 | [Beyond the Payload](https://arxiv.org/abs/2608.30686) | 仓库投毒效果依赖用户调用方式 | 摘要；作者注明 EMNLP 2026 Main，未独立核对 proceedings |
| 9 | [ADeptS-Bench](https://arxiv.org/abs/2608.26204) | 跨设备 GUI safety、歧义消解、良恶配对 | 摘要；论文写 upon publication，仓库未成功验证 |
| 10 | [SPA](https://arxiv.org/abs/2608.27234) | Persistent agent；plan-first IFC、跨 query artifact 标签 | 关键章节；严防泄漏同时有明显 utility 下降 |
| 11 | [Safety Does Not Compose](https://arxiv.org/abs/2608.27141) | 跨轮持久风险状态、non-decaying LoopHarness | 摘要；理论条件和实验协议不能当全面部署验证 |
| 12 | [The Framing Gap](https://arxiv.org/abs/2608.27092) | 将泄漏任务重包装使表层防御失效 | 摘要；synthetic canary/mock tools |
| 13 | [The Guard That Cried Wolf](https://arxiv.org/abs/2608.27009) | CautiousBench；危险名称导致合法行为被误拒 | 全文；资源 release 声明尚未找到实际链接 |
| 14 | [When Context Gets Root](https://arxiv.org/abs/2608.27299) | Harness 将低信任上下文提升成高权限指令 | 摘要；包括持久目标和调度 |
| 15 | [StepGuard](https://arxiv.org/abs/2608.24777) | Step-level guard，安全—效用平衡 | 全文及关键附录；代码、4B 模型、7k 数据入口公开；EMNLP 2026 为作者声明 |
| 16 | [TrustShiftProbe](https://arxiv.org/abs/2608.23763) | MCP 先建立信任再变坏；异常信号防御 | 摘要；防御后仍有显著残余攻击成功 |
| 17 | [Beyond the Mandate / AP2](https://arxiv.org/abs/2608.23858) | Agent payment 协议生命周期安全分析 | 摘要；系统级范围过宽 |
| 18 | [WebMCP-Phalanx](https://arxiv.org/abs/2608.24017) | Browser principal、capability、隔离低信任内容 | 摘要；“AAAI 2027”备注不等于已录用 |
| 19 | [What Guides the Agent?](https://arxiv.org/abs/2608.24022) | Attnlocate 定位行为引导文本，再判断来源权限 | 摘要；需要白盒 attention，算力/实现成本较高 |
| 20 | [Poisoning Agentic Alpha](https://arxiv.org/abs/2608.24069) | 多 agent 交易中的角色和拓扑攻击传播 | 摘要；不推荐搭完整交易平台 |
| 21 | [Beyond the Editing Canvas](https://arxiv.org/abs/2608.25880) | OOXML 人眼显示与解析器输入证据不一致 | 关键章节；偏文档解析和系统安全 |
| 22 | [EVOMAL](https://arxiv.org/abs/2608.25776) | 自进化 coding agent 把污染写入自己生成的 skills | 摘要/引言；持续多轮复现成本高 |
| 23 | [SkillShield](https://arxiv.org/abs/2608.25817) | 离线合成安全 skills，运行时提示防御 | 关键章节；静态攻击下有效不代表 adaptive robustness |
| 24 | [“Humans welcome to observe”: Moltbook](https://arxiv.org/abs/2602.10127) | Agent 社交网络实证观察 | 摘要；不是控制/防御方法 |
| 25 | [SkillJect](https://arxiv.org/abs/2602.14211) | Skill supply chain 闭环注入 | 摘要；v3 标题已改为 Effectively Automating Skill-Based Prompt Injection for Skill-Enabled Agents，列表仍为旧标题 |
| 26 | [MCPShield](https://arxiv.org/abs/2602.14281) | 调用前探测、运行时受控执行、事后分析 | 摘要；认知安全层 |
| 27 | [Safety in Embodied AI](https://arxiv.org/abs/2605.02900) | Embodied safety 综述 | 主源摘要已核；列表写 2026/01，但链接及论文时间不对应，不能据列表月份断言发表时间 |
| 28 | [Beyond Max Tokens](https://arxiv.org/abs/2601.10955) | 工具调用链造成隐蔽资源放大 | 关键章节；代码写将公开，不能依赖现成实现 |
| 29 | [AgenTRIM](https://arxiv.org/abs/2601.12449) | 读/写工具隔离、风险检查和状态管理 | 全文；官方 GitHub 仍为 Coming Soon；EMNLP 2026 Findings 为作者注明 |
| 30 | [MiniScope](https://arxiv.org/abs/2512.11147) | OAuth scope 最小权限优化 | 关键章节；scope 粒度不等于参数级授权 |
| 31 | [Explainable and Fine-Grained Safeguarding / XGGuard](https://arxiv.org/abs/2512.18733) | 多 agent 图异常检测，可解释细粒度定位 | 摘要；需图表示和系统轨迹 |
| 32 | [SoK: Security and Safety in the MCP Ecosystem](https://arxiv.org/abs/2512.08290) | MCP 安全与安全性概念/威胁地图 | 摘要；综述 |
| 33 | [MCP Does Not Stand for Misuse Cryptography Protocol](https://arxiv.org/abs/2512.03775) | MCP 服务器密码学误用静态分析 | 摘要；CPU 可做小子问题，跨语言全框架太大 |
| 34 | [Trusted AI Agents in the Cloud](https://arxiv.org/abs/2512.05951) | Cloud Omega、可信执行/机密计算 | 摘要；需要特殊云硬件，排除 Colab |
| 35 | [Hiding in the AI Traffic](https://arxiv.org/abs/2511.15998) | MCP 网络/红队指挥通信 | 摘要；不推荐作为此 capstone 主线 |
| 36 | [Towards Automating Data Access Permissions in AI Agents](https://arxiv.org/abs/2511.17959) | 预测用户的数据授权偏好 | 摘要；有 [IEEE S&P 2026 DOI](https://doi.org/10.1109/SP63933.2026.00018)，预测准确不等于可安全自动授权 |

## 研究地图

1. **动作是否真的被授权**：CautiousBench、Influence Is Not Authority、StepGuard、MiniScope、AgenTRIM。
2. **状态跨轮以后还能否信任**：SPA、LoopHarness、Safe to Resume、EVOMAL。
3. **工具/skills/harness 供应链**：SkillJect、TrustShiftProbe、MCPShield、When Context Gets Root。
4. **防御是否仍让正常任务完成**：StepGuard、AgenTRIM、CautiousBench、ADeptS。
5. **模型之外的协议和执行保证**：AP2、WebMCP、签名委托、机密计算、MCP 静态分析。

对单人、10 周、Colab 条件，第一、二、四条更合适：冻结小模型、离线轨迹、mock tools、确定性标签；尽量避免 GUI、多 agent 和真实云基础设施。

## 重点资源审计与论文边界

### StepGuard

[代码](https://github.com/zheng977/StepGuard)、[4B 模型](https://huggingface.co/ninty-seven/StepGuard)、[7k 数据](https://huggingface.co/datasets/ninty-seven/stepguard_data)入口公开。论文训练用了 **4×H200**，不适合 Colab 重训；运行时 agent 是更大的 Qwen3.6-35B-A3B。建议仅冻结使用 4B guard，单卡、batch 1、4–8k 上下文。4-bit 推理适配是工程估算，尚未实测。

不能只引用平均 ASR：AgentDyn utility 从 73.3 降至 66.7，AgentHarm completion 从 70.9 降至 52.8。其错误分析显示授权隐私、多步依赖和合法敏感工具仍是困难情形。StepGen 合成引擎的计划公开状态与已公开模型/训练数据应区分。[全文](https://arxiv.org/html/2608.24777v1)

### AgenTRIM

[官方仓库](https://github.com/FujitsuResearch/AgenTRIM)当前为 Coming Soon，不能作为现成可复现工程依赖。Selective checks 依赖工具语义、执行状态和 LLM 判断；论文延迟约 4.92→8.84 秒，成本约翻倍。已经评测状态管理器被攻击，不能把这一点当研究空白。[全文](https://arxiv.org/html/2601.12449v2)

### CautiousBench

756 对可判定良恶 twins × 3 名称等级，另有 undecidable 情形。保留动作、只改授权事实是其核心；简单重做危险名称导致误拒，新增价值有限。生成器公开声明尚无本次核到的代码入口。[全文](https://arxiv.org/html/2608.27009v1)

### Escalation

[GitHub](https://github.com/wiser-human-experimental/evilgenie-escalation)有实验、验证器、分析脚本，并链接[公开运行数据](https://huggingface.co/datasets/WiserHumanExperimental/evilgenie-escalation)。原实验基于 9 道有缺陷的困难题，预筛选 baseline hacking≥8% 的模型。“无显著性能代价”不是等价性证明；正常题在论文主要设计中只作为 baseline negative control。可扩展小模型错误上报代价，但完整 frontier 实验依赖付费 API 和 Docker。[全文](https://arxiv.org/html/2608.29460v2)

### 其他资源风险

- [ADeptS-Bench 仓库](https://github.com/facebookresearch/adepts-bench)：本次未能成功验证实际公开代码；论文发布承诺不能替代仓库核验。
- Beyond Max Tokens：正文写代码将公开，不能预设可直接运行。
- SkillShield：固定攻击条件下的效果不能推及自适应攻击；其低误拒数字来自 benign descriptions，不能等同完整正常任务成功率。
- SPA：跨 query 的 IFC 标签/持久 artifact 安全已有工作基础；严格控制可能付出 utility 代价，不能只汇报 ASR。
- Trusted AI Agents in the Cloud：涉及 AMD SEV-SNP、机密 GPU/H100 一类硬件，不是普通 Colab 课题。

## 与“历史压缩—授权证据—ledger”拟题的直接重叠

**判断：原样新颖性偏低。** 可以做扎实 capstone，但应定位为复现、受控评测和小模型扩展。尤其 2026 年 9 月的 EAL-Bench 连撤销、来源、持续更新权限、event sourcing、误拒代价都已覆盖。

| 已有工作 | 已覆盖内容 | 对拟题的影响 |
|---|---|---|
| [Governance Decay / ConstraintRot](https://arxiv.org/abs/2606.22528) | Full history、截断/摘要、约束遗失、确定性工具动作判定、约束 pinning；还做 summarizer×agent、中文/西语、多轮 | 不能把压缩后违反原规则或保留规则可缓解当新发现 |
| [The Compaction Cliff / Knowledge Triage](https://arxiv.org/abs/2608.22752) | 按内容类型保留、压缩/检索/分解、source-authority weighting、预算约束、下游行为 | 简单 structured ledger 或来源加权保留也已有 |
| [AI Guardrail Survival under Single-Cycle Agentic Self-Summarization](https://arxiv.org/abs/2608.11392) | 规则保留但谓词/限定条件退化；behavioral replay；external constraint registry | 不能只看文本留存而要测行为，也是已有结论 |
| [GateMem](https://arxiv.org/abs/2606.18829) | 多主体记忆中权限变化、删除、utility/access control/forgetting、不同 memory 比较 | 动态授权记忆和安全—效用—成本权衡已有 |
| [EAL-Bench / Agent Memory Is a Surface for Endogenous Authorization Laundering](https://arxiv.org/abs/2609.01836) | 权限、限制、撤销、来源被洗掉；memory writer→executor 错误传播；source-event 验证与 bounded event sourcing；误拒权衡 | 与拟题最直接，动态 ledger 思路也重叠 |

额外阅读边界：Governance Decay 阅读主文方法/结果/局限；Compaction Cliff 阅读方法/结果/局限；GateMem 阅读方法、结果、baseline 和附录实验设计；Guardrail Survival 只核摘要和 PDF 入口。**EAL-Bench 只核主源摘要，未读全文，不能声称排除它所有重叠。**

额外资源：

- [GateMem 代码](https://github.com/rzhub/GateMem)与[数据](https://huggingface.co/datasets/Ray368/GateMem)实际可打开，91 episodes、2,218 checkpoints。适合取 office/household 子集。原任务是回答信息的 memory benchmark；改成 tool-call guard 后属于派生任务，不能直接沿用原评测分数名。
- [Knowledge Triage 代码](https://github.com/searchsim-org/cikm26-knowledge-triage)实际存在，含实验与结果；完整 AgentArtifactCorpus 有申请/DUA，仓库含 327 个脱敏样本，不必等待完整数据才能实现 baseline。
- Governance Decay 在文中声明发布材料，但本次未核到实际作者仓库，不能承诺即取即用。
- EAL-Bench 的资源尚未核验；若最终选此方向，必须优先读全文并检查资源。

## 单人 10 周候选设计

### 1. 有限上下文下，小型 guard 对当前授权状态的可靠性审计

建议英文题名：*Budget-Constrained Authorization Checking for Small Agent Guards*。定位为已有 memory-governance 工作在小型 step guard 上的受控扩展，不宣称发明授权记忆。

- 范围：先 120 对、最多 200 对，仅 email/file sharing 两域；有效授权、撤销、可信来源、过期四类。配对的最终动作保持相同。
- 条件：full history、last-k、普通摘要、verbatim pinning、Knowledge Triage、structured ledger；ledger 分人工 oracle 和自动抽取。
- 模型：冻结 StepGuard-4B 加一个通用 3–4B；离线审查为主，20–30 个动态 mock demo 为辅。
- 指标：非法放行、合法误拒、配对正确翻转、授权字段完整性、陈旧授权残留、token/延迟。允许 unknown 时报告覆盖率—风险曲线，不能靠全部 unknown 降错误。
- 控制：同 token budget；oracle/自动 ledger 分开；full history 仅作 baseline；按源轨迹/模板分割数据，避免改写泄漏。
- 算力：16GB 单卡量化、batch 1、先 4k context。120 pairs×2×6 representations×2 models≈2,880 次短判定，缓存摘要；第 2 周实测吞吐后决定扩规模。
- 风险：必须先读 EAL 全文，再确定基于它的明确扩展。可做性高；论文新颖性低到中，不能承诺可投稿。

### 2. 预算有限时，哪些工具调用值得重新运行 guard？

比较每步检查、仅写操作、规则触发、授权状态变化触发。用 StepGuard 和 50–100 条公开或派生轨迹，固定预算，测漏检、合法完成率、检查次数、延迟 Pareto；加入撤销、跨工具数据流等读操作也危险的情形。

CPU 状态机加冻结 4B 即可。主要价值是可解释的 cost–risk tradeoff 和失败模式。AgenTRIM/MiniScope 已覆盖风险和权限控制，不能把少检查几次当新方法；更适合作为题 1 工程扩展。

### 3. 小 coding agent 的缺陷上报：减少投机，还是增加误报？

借用 Escalation 的 policy/channel，构造 30–40 道可确定判分的小 coding tasks，各有正常/测试器缺陷配对。比较无措施、仅政策、仅上报、两者联合，增加上报须附可复现反例的变体。

指标：真实解题率、测试器篡改率、缺陷检出、正常题误报、放弃率、额外 token。一个小模型作主实验，另一个复核。本地 CPU 沙盒加 Colab 3–7B；原仓库 API 层需适配。先能力筛选与降低题目难度，避免把不会解题误解为 safety 行为。上报渠道本身已有，扩展价值在小模型和正常任务代价。

### 4. 执行恢复时，旧授权何时必须重新确认？

只实现一个模拟工作流：批准发送文件→暂停→文件内容/收件人/权限变化→恢复。对比直接 resume、全部重验、绑定 action hash/permission version 的最小重验。

指标：过期授权执行、重复副作用、合法恢复误阻塞、重验次数、延迟。CPU 状态机即可，LLM 只产生候选操作；两类工具、三类变化足够。Safe to Resume、SPA、EAL 已覆盖相关原则，主价值是窄范围实现与权衡评测；安全工程可做性高，ML 研究味较弱。

推荐排序：**1（明确复现扩展）＞3＞4＞2**。如果导师要求明显可投稿的新问题，现有证据不足以承诺题 1 原样有 novelty；优先读 EAL-Bench，再选它未覆盖的小 guard 校准、资源约束或具体错误机制。
