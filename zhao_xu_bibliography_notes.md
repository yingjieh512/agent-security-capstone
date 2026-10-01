# Zhao (Bill) Xu 许钊：核验书目与 DeepMM 阅读记录

检索日期：2026-09-29。对象：UCLA Cho-Jui Hsieh 组 PhD、HKUST Hao Liu / Hui Xiong 组 MPhil；ORCID `0009-0009-0974-4974`。以本人主页、本人 ORCID 与原论文/作者仓库交叉核验。不能把所有同名 Zhao Xu 的搜索结果算作他的作品，也不能把 arXiv 和会议版简单重复计数。

## 已核实的 8 个发表/预印本条目（含 2 对会议与期刊扩展）

1. **DeepMM: Deep Learning Based Map Matching with Data Augmentation.** Kai Zhao, Jie Feng, Zhao Xu, Tong Xia, Lin Chen, Funing Sun, Diansheng Guo, Depeng Jin, Yong Li. SIGSPATIAL 2019, pp. 452–455. DOI: https://doi.org/10.1145/3347146.3359090 。作者公开稿旧地址 https://vonfeng.github.io/files/SIGSPATIAl-DeepMM.pdf 现在 404，但搜索引擎缓存仍可访问各节正文；我已读取缓存中的四页正文各节。代码：https://github.com/vonfeng/DeepMapMatching 。
2. **DeepMM: Deep Learning Based Map Matching With Data Augmentation.** Jie Feng, Yong Li, Kai Zhao, Zhao Xu, Tong Xia, Jinglin Zhang, Depeng Jin. IEEE Transactions on Mobile Computing 21(7), pp. 2372–2384, 2022；2020 early access（本人主页因此标 TMC 2020）。DOI: https://doi.org/10.1109/TMC.2020.3043500 。是前一篇期刊扩展。本轮只能核验摘要、公开代码和书目信息，未取得期刊全文；不应宣称已读完该 13 页版本。作者主页误写 Lin Chen，最终论文/代码引用为 Jinglin Zhang。IEEE 期刊目录支持 2022 卷期：https://www.comsoc.org/system/files/2022-08/Publications_Contents_Digest_2022_Jul.pdf 。
3. **Adversarial Tuning: Defending Against Jailbreak Attacks for LLMs.** Fan Liu, Zhao Xu, Hao Liu. arXiv:2406.06622, 2024-06-07. https://arxiv.org/abs/2406.06622 。本轮未核实后续正式 venue。
4. **Bag of Tricks: Benchmarking of Jailbreak Attacks on LLMs.** Zhao Xu, Fan Liu, Hao Liu. NeurIPS 2024, Advances in Neural Information Processing Systems 37, pp. 32219–32250. https://arxiv.org/abs/2406.09324 。Beta 主页 NeurIPS’25 标签错误；其 BibTeX 及 arXiv 明确为 2024。正式记录：https://dblp.org/rec/conf/nips/Xu0L24.html 。
5. **JAILJUDGE: A Comprehensive Jailbreak Judge Benchmark with Multi-Agent Enhanced Explanation Evaluation Framework.** Fan Liu, Yue Feng, Zhao Xu, Lixin Su, Xinyu Ma, Dawei Yin, Hao Liu. arXiv:2410.12855, 2024. https://arxiv.org/abs/2410.12855 。旧主页把标题链接误指向 Bag of Tricks，须用此正确链接；未核实正式发表 venue。
6. **Urban Foundation Models: A Survey.** Weijia Zhang, Jindong Han, Zhao Xu, Hang Ni, Hao Liu, Hui Xiong. KDD 2024 Tutorial Track Paper, pp. 6633–6643. https://doi.org/10.1145/3637528.3671453 。会议版与下面期刊扩展应区分。
7. **LLMLight: Large Language Models as Traffic Signal Control Agents.** Siqi Lai, Zhao Xu, Weijia Zhang, Hao Liu, Hui Xiong. KDD 2025 V. 1, pp. 2335–2346. https://doi.org/10.1145/3690624.3709379 ，公开全文 https://arxiv.org/abs/2312.16044 。2023 arXiv 初稿标题 Large Language Models as Traffic Signal Control Agents: Capacity and Opportunity；2024-12 v5 更名为 LLMLight。属于同一研究。
8. **Towards Urban General Intelligence: A Review and Outlook of Urban Foundation Models.** Weijia Zhang, Jindong Han, Zhao Xu, Hang Ni, Tengfei Lyu, Hao Liu, Hui Xiong. ACM Transactions on Intelligent Systems and Technology, 2026. DOI: https://doi.org/10.1145/3821528 ，最新公开稿 https://arxiv.org/abs/2402.01749v3 （2026-03-22）。作者仓库明确 2025-01 substantially extended version、2026-03 accepted by TIST：https://github.com/usail-hkust/Awesome-Urban-Foundation-Models 。第一作者主页确认 TIST 2026：https://willzhang3.github.io/ 。Crossref publisher metadata 与目标 ORCID 完全吻合。日期字段存在数据库差异（网页二手索引 2026-07，当前 Crossref 2026-09-29）；最终建议只写 TIST 2026。

## 核验范围与排除

- 旧主页 https://zhaohsu.top/ 列 7 项，beta https://zhaohsu.top/zhaoxu_beta/ 仅 2 篇 selected；旧主页的 survey 标题与链接已替换成扩展版，因此最终完整书目宜将 KDD 原版与 TIST 扩展版分开列。
- 公共 ORCID Works API：https://pub.orcid.org/v3.0/0009-0009-0974-4974/works 。获取原始返回保存于 `/tmp/zhaoxu-orcid.json`；含上述作品及其 arXiv/正式版重复记录。
- DBLP 消歧页 https://dblp.org/pid/96/5046-6.html 还列 **Intelligent decision making for UAV based on Monte Carlo Simulation**（ICARCV 2018，Yunhong Ma 等）。目标本人主页与 ORCID 均未列，身份未交叉证实，故不纳入已确认的 8 项。DBLP 自身也存在同名作者记录归并风险。
- 本轮未找到另一篇可由本人 ORCID/主页或共同作者确认的 2025–2026 新研究；不能据此保证不存在未公开或未更新成果。

## DeepMM 方法与启发（2019 全文缓存；TMC 摘要及代码）

2019 论文把嘈杂、稀疏 GPS 到道路序列的匹配视为 seq2seq：100m 网格嵌入、LSTM 编解码器、attention。两种增广分别为真实轨迹降采样加高斯噪声，以及最短路加 waypoint 扰动后再模拟观测。北京 12,436 条高质量轨迹由 HMM 生成近似真值。60s 采样、100m 噪声下 DeepMM 准确率 0.66，HMM 0.55、无 attention 0.63；增广很关键。

TMC 的公开摘要仍是 latent-space trajectory2road 与 attention 路线；代码包含 GraphHopper 轨迹生成、降采样/加噪声、PyTorch 模型、FMM/ST-Matching 基线。没有期刊全文，不能确定相对短文每一项新增贡献。

对本次 solo + Colab capstone 的推论：可用它解释他长期关心“输入退化下的可靠性”，但不建议为了和早期工作贴近而重建 GIS/轨迹训练系统。与当前 trustworthy FM 主线最自然的连接是：明确列举现实扰动、测试分布变化、比较数据增广或轻量修复；这是一种研究方法的延续，并不意味着他当前仍优先研究地图匹配。上述推论不是论文作者原话。
