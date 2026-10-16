# Jev 对抗轨迹实验：精简审计副本

本目录保存 100 个 ATBench 父轨迹的固定选择清单、三臂配对判决、汇总统计和运行哈希，以及开发集汇总。`guard_holdout` 对应 Jev-Guard v3.2 2B；`typesafe_1_13` 和 `typesafe_1_14` 分别对应 TypeSafe System One 的固定版本。`cross_judge` 保留相同父轨迹上的离线比较。

`pairs.jsonl` 和 `per_parent.jsonl` 只记录公开数据集 ID、标签、模型判决、概率与错误状态。完整实验快照已保存在仓库的 [`outputs/`](../../outputs/)：它包含派生的 `atbench_rows.jsonl`、模型输入 `states.jsonl`、可逆逐事件 `manifest.jsonl` 和逐请求 `predictions.jsonl`。虽然 `.gitignore` 匹配 `outputs/`，本次仍将其中现有的 68 个文件显式强制加入 Git；之后新生成的文件仍默认被忽略。规范的 ATBench 下载文件仍在未入库的 `data/raw/`。原始及派生轨迹中的凭据和邮箱形状文本随数据原样保留，不能据此认定它们是真实凭据；实际 TypeSafe API 密钥未包含在归档中。本精简副本本身没有 API 密钥、授权头、完整提示或原始工具结果。

## 来源与完整性

下表所有文件均从本仓库 [`outputs/`](../../outputs/) 中的对应实验产物逐字节复制。复制前计算来源文件 SHA-256，复制后重新计算来源和目标 SHA-256；三者逐项一致。表中的哈希可用于检查原产物与本精简副本。

| 本目录文件 | 仓库内原产物 | SHA-256 |
| --- | --- | --- |
| `holdout_selection.json` | [`outputs/jev-adversarial-holdout-selection-2026-10-15.json`](../../outputs/jev-adversarial-holdout-selection-2026-10-15.json) | `84f71010f066fbc9edcf81fda3776b67a80e02d320355ca809477ecaed47c2a2` |
| `dev20_selection.json` | [`outputs/jev-adversarial-dev20-selection-2026-10-15.json`](../../outputs/jev-adversarial-dev20-selection-2026-10-15.json) | `2f54477192a0d9b1684118fee805231aeb2d73cf6bd45bc5b3802126bbb1ec54` |
| `guard_holdout/construction_summary.json` | [`outputs/jev-adversarial-trajectories-holdout100-tail/summary.json`](../../outputs/jev-adversarial-trajectories-holdout100-tail/summary.json) | `dc4ef0b1c4fe606d4f4ae9a0b9086b74e7382e013e4efc17ccd9d9296007a432` |
| `guard_holdout/summary.json` | [`outputs/jev-adversarial-trajectories-holdout100-tail/evaluation/summary.json`](../../outputs/jev-adversarial-trajectories-holdout100-tail/evaluation/summary.json) | `20f66f73dda5335864877a1fec0f5baec622668bba93988df8aed8093f0f1770` |
| `guard_holdout/pairs.jsonl` | [`outputs/jev-adversarial-trajectories-holdout100-tail/evaluation/pairs.jsonl`](../../outputs/jev-adversarial-trajectories-holdout100-tail/evaluation/pairs.jsonl) | `0b9aaef2c06359a1214b1a368fe61c360f075a9bdeb1bf3ef816e77ec2c6a8f6` |
| `guard_holdout/run_manifest.json` | [`outputs/jev-adversarial-trajectories-holdout100-tail/run_manifest.json`](../../outputs/jev-adversarial-trajectories-holdout100-tail/run_manifest.json) | `62939e4161a9e5c214d99b1c8afe4c9b7bc3dcb90a28c0223a7fbfebe56d5eb4` |
| `guard_holdout/health_snapshot_before.json` | [`outputs/jev-adversarial-trajectories-holdout100-tail/health_snapshot.json`](../../outputs/jev-adversarial-trajectories-holdout100-tail/health_snapshot.json) | `427c1fd23bf18623b22b5fc4d875b3b1aec32e3c1999634777a1841b894e1cc7` |
| `guard_holdout/health_snapshot_after.json` | [`outputs/jev-adversarial-trajectories-holdout100-tail/health_snapshot_after.json`](../../outputs/jev-adversarial-trajectories-holdout100-tail/health_snapshot_after.json) | `427c1fd23bf18623b22b5fc4d875b3b1aec32e3c1999634777a1841b894e1cc7` |
| `typesafe_1_13/summary.json` | [`outputs/typesafe-adversarial-holdout100-tail-jev-1.13.0/summary.json`](../../outputs/typesafe-adversarial-holdout100-tail-jev-1.13.0/summary.json) | `3a56fd7fdb30db36ff4fa87974eba3d93056a738ddccd6b43175835b5b5d75a1` |
| `typesafe_1_13/pairs.jsonl` | [`outputs/typesafe-adversarial-holdout100-tail-jev-1.13.0/pairs.jsonl`](../../outputs/typesafe-adversarial-holdout100-tail-jev-1.13.0/pairs.jsonl) | `4ba152fd94d5d2be49799b6a569411ec827f6bec59d03024dc50952421c6691b` |
| `typesafe_1_13/run_manifest.json` | [`outputs/typesafe-adversarial-holdout100-tail-jev-1.13.0/run_manifest.json`](../../outputs/typesafe-adversarial-holdout100-tail-jev-1.13.0/run_manifest.json) | `e64ccb8d4d92437ebbee760a3346680e9cd75eb110708528a1f50fdeb0831238` |
| `typesafe_1_14/summary.json` | [`outputs/typesafe-adversarial-holdout100-tail-jev-1.14.0/summary.json`](../../outputs/typesafe-adversarial-holdout100-tail-jev-1.14.0/summary.json) | `25f970cd8ec785e85121d2d13803a74dd9a8cf07b67d302d7614f22acd4c0d6a` |
| `typesafe_1_14/pairs.jsonl` | [`outputs/typesafe-adversarial-holdout100-tail-jev-1.14.0/pairs.jsonl`](../../outputs/typesafe-adversarial-holdout100-tail-jev-1.14.0/pairs.jsonl) | `e5ebce811ec53a98d03df47c946ead3a603588658c0b6be928d8f6d25289df73` |
| `typesafe_1_14/run_manifest.json` | [`outputs/typesafe-adversarial-holdout100-tail-jev-1.14.0/run_manifest.json`](../../outputs/typesafe-adversarial-holdout100-tail-jev-1.14.0/run_manifest.json) | `cba301ad70cc6d57d5d745b29eb35613c3566bd089bd46691719ca4db95b2c50` |
| `cross_judge/comparison.json` | [`outputs/jev-adversarial-trajectories-holdout100-tail/cross-judge/comparison.json`](../../outputs/jev-adversarial-trajectories-holdout100-tail/cross-judge/comparison.json) | `68827a51f58707800b2981a886611be139be38075f5c29350438d401b6d04c43` |
| `cross_judge/per_parent.jsonl` | [`outputs/jev-adversarial-trajectories-holdout100-tail/cross-judge/per_parent.jsonl`](../../outputs/jev-adversarial-trajectories-holdout100-tail/cross-judge/per_parent.jsonl) | `b1b57a966ddbcc254a73f5109c16ecb6ecac83d643e658bad2dcf6ae96989493` |
| `cross_judge/run_manifest.json` | [`outputs/jev-adversarial-trajectories-holdout100-tail/cross-judge/run_manifest.json`](../../outputs/jev-adversarial-trajectories-holdout100-tail/cross-judge/run_manifest.json) | `be282c067edbe004cc25d532f483eb06302b0ef0d467799fd3121d42e67fb49d` |
| `development/dev7_first_summary.json` | [`outputs/jev-adversarial-trajectories-dev7/evaluation/summary.json`](../../outputs/jev-adversarial-trajectories-dev7/evaluation/summary.json) | `083495ce2eb38313a1fc49ad993cf8c30b2e015df69e89054169913047a84bd9` |
| `development/dev7_second_summary.json` | [`outputs/jev-adversarial-trajectories-dev7-v2/evaluation/summary.json`](../../outputs/jev-adversarial-trajectories-dev7-v2/evaluation/summary.json) | `3e2db4cf39b7bf43cfabc3251a1e85419f3dbf9a999dc65a16e22df4d320cfcf` |
| `development/dev20_tail_summary.json` | [`outputs/jev-adversarial-trajectories-dev20-tail/evaluation/summary.json`](../../outputs/jev-adversarial-trajectories-dev20-tail/evaluation/summary.json) | `7e89319953f67adcccf5bc361bfd45790683c62fe0e7654e4bbcaf12788fa4ac` |
| `development/dev7_construction_summary.json` | [`outputs/jev-adversarial-trajectories-dev7/summary.json`](../../outputs/jev-adversarial-trajectories-dev7/summary.json) | `ac7dae62c8f5338ffcd8e6411a266da94385b8f4e3115000221bc110e8287d00` |

## 重建与离线复核

1. 按 [`data/README.md`](../../data/README.md) 从固定版本下载 ATBench；下载器验证 1,000 条记录和源文件 SHA-256。构造器默认使用仓库内固定的 Jev-Guard 基线预测及其汇总。
2. 读取 `holdout_selection.json` 的 `selected_ids`，在仓库根目录运行 [`scripts/construct_jev_adversarial.py`](../../scripts/construct_jev_adversarial.py)，参数为 `--selection ids --ids <逗号连接的 selected_ids> --families tail_safety --output-dir <新的 outputs 目录>`。`dev20_selection.json` 用于开发阶段的 20 条选择。对照 `guard_holdout/construction_summary.json` 和运行清单中的源、输入与代码哈希。
3. 若相应服务仍可访问，用 [`scripts/eval_jev_adversarial_pairs.py`](../../scripts/eval_jev_adversarial_pairs.py) 和 [`scripts/eval_typesafe_adversarial_pairs.py`](../../scripts/eval_typesafe_adversarial_pairs.py) 重放完全相同的 300 条 `states.jsonl` 输入。TypeSafe 需由操作者本地提供 API 密钥；不要将密钥或路径写进仓库。在线输出可能随服务版本和时间变化。
4. 无需模型服务，可直接用三个目录下的 `pairs.jsonl` 与 `summary.json` 运行 [`scripts/compare_jev_adversarial_judges.py`](../../scripts/compare_jev_adversarial_judges.py)，将 `--guard-dir`、`--typesafe-1-13-dir`、`--typesafe-1-14-dir` 指向本目录相应子目录。由此可复核配对表、差中差及 bootstrap 汇总；`cross_judge/per_parent.jsonl` 保存逐父比较。

这些配对结果足以审查报告中的统计结论。进一步可直接核对已归档的[可逆逐事件清单](../../outputs/jev-adversarial-trajectories-holdout100-tail/manifest.jsonl)、[300 条模型输入](../../outputs/jev-adversarial-trajectories-holdout100-tail/states.jsonl)、[ATBench 风格三臂轨迹](../../outputs/jev-adversarial-trajectories-holdout100-tail/atbench_rows.jsonl)与[逐请求判定](../../outputs/jev-adversarial-trajectories-holdout100-tail/evaluation/predictions.jsonl)；固定数据源和构造脚本仍支持独立重建。
