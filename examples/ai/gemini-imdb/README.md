# Gemini IMDB Structured Extraction Example

This example runs `ai.google` with `gemini-2.5-flash-lite` against a small IMDB
sample (first 10 rows from IMDB review db) and returns structured enrichment fields.
Rows are read from `imdb_first10.csv` at runtime via `core.csv.read`.

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

## Data source

`process.bpg.yaml` reads from:

```text
examples/ai/gemini-imdb/imdb_first10.csv
```

The reader auto-assigns `row_id` values (1-based by file order), so `row_ids: [1,2,3]`
selects the first three rows in the CSV.
