# Custom Provider Development (Example: OCR Node)

This guide explains how to implement node code that is not built into BPG, such as OCR.

## 1. Declarative-First Provider Registry

Custom providers are loaded from a YAML registry file:

- default auto-discovery: `bpg.providers.yaml` or `bpg.providers.yml` in current directory
- explicit override: `--providers-file <path>`

Registry format:

```yaml
providers:
  vision.ocr: ocr_provider:OcrProvider
```

Equivalent object form:

```yaml
providers:
  vision.ocr:
    class: ocr_provider:OcrProvider
```

Rules:

- key (`vision.ocr`) must match class `provider_id`
- class must subclass `bpg.providers.base.Provider`
- entrypoint uses `module:Class`

## 2. Fresh Repo + `uv tool` Workflow

If a user has only installed `bpg` via `uv tool`, they can still run custom providers locally by keeping provider code next to their process files.

Example local layout:

```text
my-process/
  process.bpg.yaml
  bpg.providers.yaml
  ocr_provider.py
```

Then run:

```bash
bpg plan process.bpg.yaml
```

No `--providers-file` is needed if using the default filename.

## 3. Add a New Provider Class

Create `ocr_provider.py` (or place in your package/module path):

```python
from __future__ import annotations

from typing import Any, Dict, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)


class OcrProvider(Provider):
    provider_id = "vision.ocr"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        image_path = input.get("image_path")
        if not isinstance(image_path, str) or not image_path:
            raise ProviderError("invalid_input", "vision.ocr requires input.image_path", False)

        # Replace with real OCR call (for example pytesseract/easyocr/etc).
        text = f"OCR_PLACEHOLDER({image_path})"

        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": {"text": text}},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        _ = config
        return {"services": [], "required_env": [], "optional_env": []}
```

## 4. Register the Provider Declaratively

Create `bpg.providers.yaml`:

```yaml
providers:
  vision.ocr: ocr_provider:OcrProvider
```

You can also use a non-default filename and pass:

```bash
bpg plan process.bpg.yaml --providers-file ./my.providers.yaml
```

## 5. Define OCR Node in Process YAML

```yaml
types:
  OcrIn:
    image_path: string
  OcrOut:
    text: string

node_types:
  ocr@v1:
    in: OcrIn
    out: OcrOut
    provider: vision.ocr
    version: v1
    config_schema: {}

nodes:
  extract_text:
    type: ocr@v1
    config: {}

trigger: extract_text
edges: []
```

Validate/compile:

```bash
uv run bpg plan process.bpg.yaml
```

## 6. Package Runtime Code for Local/Docker

Current package local-build mode includes:

- `Dockerfile`
- `pyproject.toml`
- `uv.lock`
- `src/**/*.py`

Implication:

- If custom provider code lives in a source checkout under `src/`, it is included in package artifacts.
- If using `uv tool` with ad-hoc local files (for example `ocr_provider.py` in a separate process repo), that file is not automatically copied into package artifacts.

## 7. Add External OCR Dependencies

If OCR needs Python deps:

```bash
uv add pytesseract pillow
```

If OCR needs OS packages (for example Tesseract binary), update `Dockerfile`:

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
```

Then:

- local runtime: `uv run bpg up process.bpg.yaml`
- package artifact: `uv run bpg package process.bpg.yaml`

## 8. Testing Checklist for Custom Providers

- Unit test provider methods (`invoke`, `poll`, `await_result`, `cancel`).
- Add a process YAML example using your provider and run `bpg plan`.
- Add a system test that parse/validate/compile succeeds for the example.
- Verify `bpg up` and packaged compose both run with required env/deps.

## 9. Future Improvement (Not Implemented Yet)

For fully portable package artifacts from non-source repos, BPG could add explicit custom-code bundling hooks (for example copying registry modules into package output). Current implementation favors source-tree providers for packaging.
