# Gemini IMDB Structured Extraction Example

This example runs `ai.google` with `gemini-2.5-flash-lite` against a small IMDB sample (first 10 rows from `~/Downloads/IMDB.csv`) and returns structured enrichment fields.

## Files

- `process.bpg.yaml`: process definition using provider `ai.google`
- `imdb_first10.csv`: source sample data (header + first 10 rows)
- `input.yaml`: run payload (`row_ids` list)

## Required env var

The AI node reads the API key from `GOOGLE_API_KEY` (`api_key_env: GOOGLE_API_KEY` in node config).

```bash
export GOOGLE_API_KEY='your-google-ai-studio-key'
```

## Run

From repo root:

```bash
source .venv/bin/activate
uv run bpg apply examples/ai/gemini-imdb/process.bpg.yaml
uv run bpg run gemini-imdb-structured-extraction --input examples/ai/gemini-imdb/input.yaml
uv run bpg status --process gemini-imdb-structured-extraction
```

## Trigger Input (`row_ids`)

The trigger expects:

```yaml
row_ids: [1, 2, 3]
```

In the dashboard, you can enter:
- `1,2,3`
- `1 2 3`
- `1-3`

## Captured Artifacts

The process declares output artifacts:
- `enriched_items` (JSONL from `enrich.out.items`)
- `run_output` (JSON from final process `output`)

They are written under:

```text
.bpg-state/runs/<run_id>/artifacts/
```

## Regenerate input from CSV

If you replace `imdb_first10.csv`, regenerate `input.yaml`:

```bash
source .venv/bin/activate
uv run python - <<'PY'
import csv
from pathlib import Path
import yaml

csv_path = Path('examples/ai/gemini-imdb/imdb_first10.csv')
out_path = Path('examples/ai/gemini-imdb/input.yaml')
row_ids = []
with csv_path.open(newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for idx, row in enumerate(reader, start=1):
        row_ids.append(idx)
out_path.write_text(yaml.safe_dump({'row_ids': row_ids[:3]}, sort_keys=False), encoding='utf-8')
print(f'wrote {out_path} selecting rows: {row_ids[:3]}')
PY
```
