"""Package the mail capstone as a portable deterministic source and results archive."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
FREEZE = "reports/policy_transfer/freeze.json"
PREFIX = "solo-mail-audit/"
DEFAULT_ZIP = ROOT / "outputs" / "mail_capstone" / "solo-mail-audit.zip"
PROJECT_FILES = (
    "LICENSE",
    "examples/mail_audit/full_packet.json",
    "examples/mail_audit/approved_subset.json",
    "examples/mail_audit/count_limit.json",
    "examples/mail_audit/local_case.json",
    "src/trajectory_audit/__init__.py",
    "src/trajectory_audit/data.py",
    "src/trajectory_audit/download.py",
    "scripts/plan_mail_policy_change.py",
    "scripts/run_solo_mail_audit.py",
    "scripts/mail_audit_workspace.py",
    "scripts/demo_mail_policy_workspace.py",
    "scripts/run_mail_case.py",
    "scripts/run_mail_capability_study.py",
    "scripts/reproduce_mail_capstone.py",
    "scripts/package_mail_capstone.py",
    FREEZE,
    "reports/policy_transfer/results.json",
    "reports/solo_mail_audit/README.md",
    "reports/solo_mail_audit/protocol.md",
    "reports/solo_mail_audit/results.json",
    "reports/solo_mail_audit/final_protocol.md",
    "reports/solo_mail_audit/final_report.md",
    "reports/solo_mail_audit/workspace_demo.json",
    "reports/solo_mail_audit/capability_results.json",
    "capstone/solo_mail_audit_proposal_zh.pdf",
    "capstone/solo_mail_audit_final_zh.pdf",
    "tests/test_solo_mail_audit.py",
    "tests/test_mail_audit_workspace.py",
    "tests/test_mail_capability_study.py",
    "tests/test_custom_mail_case.py",
    "tests/test_mail_capstone_release.py",
)
README = """# 邮件代理授权策略变更后的审计日志迁移

[最终报告（PDF）](capstone/solo_mail_audit_final_zh.pdf) · [最终报告与演示说明](reports/solo_mail_audit/final_report.md) · [最终实验协议](reports/solo_mail_audit/final_protocol.md)

## 复现全部实验

在本文件所在目录运行，需要 Python 3.10+，支持 macOS 或 Linux 的 arm64 和 x86-64 主机。

```sh
python3 scripts/reproduce_mail_capstone.py
```

首次运行下载并校验本机适用的 Mailpit v1.34.0。已有官方压缩包时，可用以下命令离线安装并运行。

```sh
python3 scripts/reproduce_mail_capstone.py --mailpit-archive /path/to/mailpit-release.tar.gz
```

后续运行复用本地后端。命令启动回环 SMTP 服务，依次验证跨版本发送演示、56 个策略切换和来源字段缺失实验，逐项比对三个归档 JSON。成功输出位于 `outputs/mail_capstone/reproduced/`。运行这三项实验只需要 Python 标准库和固定版本的 Mailpit。可使用 `SHA256SUMS` 核对包内文件。

## 审计自己编写的邮件样例

完成首次安装后，可复制 `examples/mail_audit/local_case.json`，修改授权范围、送达内容和中途切换的策略。沿用样例中的合成收件人地址，可在本机运行一次 SMTP 发送并比较审计判定与持久化邮件的参考结果。

```sh
PYTHONPATH=src:scripts python3 scripts/run_mail_case.py examples/mail_audit/local_case.json
```

## 源码与结果

- [版本化审计工作区](scripts/mail_audit_workspace.py)保存每次发送的固定策略版本和认证回执。
- [字段迁移工具](scripts/plan_mail_policy_change.py)根据策略和来源能力计算采集差异。
- [原始策略迁移试验](reports/solo_mail_audit/README.md)和[来源能力结果](reports/solo_mail_audit/capability_results.json)保留复核所用的分母与配置。
- `examples/mail_audit/` 包含可直接交给工具的 JSON。执行独立脚本时，从本目录设置 `PYTHONPATH=src:scripts`。
- 可选回归测试使用 pytest。在装有 pytest 的环境中运行 `PYTHONPATH=src:scripts RUN_LOCAL_MAILPIT=1 python3 -m pytest tests`。
"""


def add_file(archive, name, data):
    entry = ZipInfo(PREFIX + name, date_time=(2020, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    archive.writestr(entry, data)


def package(destination: Path):
    if destination.suffix.lower() != ".zip":
        raise ValueError("Output path must end in .zip")
    pins = json.loads((ROOT / FREEZE).read_text())["files"]
    names = sorted(set(PROJECT_FILES) | set(pins))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as tmp:
        output = Path(tmp) / "release.zip"
        with ZipFile(output, "w") as zipped:
            manifest = []
            for name in ["README.md", *names]:
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise ValueError(f"Expected a project-relative path: {name}")
                data = README.encode() if name == "README.md" else (ROOT / name).read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                if name in pins and digest != pins[name]:
                    raise ValueError(f"Frozen input changed: {name}")
                add_file(zipped, name, data)
                manifest.append(f"{digest}  {name}\n")
            add_file(zipped, "SHA256SUMS", "".join(manifest).encode())
        output.replace(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_ZIP)
    args = parser.parse_args()
    package(args.out)
    print(f"Saved {args.out} (sha256 {hashlib.sha256(args.out.read_bytes()).hexdigest()})")


if __name__ == "__main__":
    main()
