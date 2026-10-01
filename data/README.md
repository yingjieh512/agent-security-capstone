# Data

`data/raw/` is ignored by Git. Download the pinned public ATBench release with:

```bash
.venv/bin/trajectory-audit download
```

The downloader verifies 1,000 unique records and SHA-256
`80c534b5f3517c872b528a2e6b64e34495206968edd184f4aed563d39f0cca09`.

ATBench is published under Apache-2.0. The project uses its released binary
trajectory label for diagnostic custom splits. Annotation rationales and taxonomy
fields are retained only for error analysis and are never included in model input.

