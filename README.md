# BPG

Business Process Graph (BPG) is a declarative workflow system for defining, packaging, and running typed business process graphs.

## Install From GitHub

Install as an application (recommended):

```bash
uv tool install "git+https://github.com/ginstrom/bpg.git"
```

or:

```bash
pipx install "git+https://github.com/ginstrom/bpg.git"
```

Then run:

```bash
bpg --help
```

## Documentation

- [User Manual](manual/USER_MANUAL.md)
- [BPG Specification](docs/bpg-spec.md)

## Local Dev Setup

```bash
uv venv
source .venv/bin/activate
uv sync
uv run bpg --help
```
