# BPG

Business Process Graph (BPG) is a declarative workflow system for defining, packaging, and running typed business process graphs.

## Install From GitHub

Install as an application (recommended):

```bash
uv tool install "git+https://github.com/<org>/<repo>.git"
```

or:

```bash
pipx install "git+https://github.com/<org>/<repo>.git"
```

Then run:

```bash
bpg --help
```

## Local Dev Setup

```bash
uv venv
source .venv/bin/activate
uv sync
uv run bpg --help
```
