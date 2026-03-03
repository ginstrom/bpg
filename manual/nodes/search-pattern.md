# Search Pattern (Ingestion + Retrieval)

This document describes the recommended BPG pattern for search systems with separate ingestion and retrieval flows.

## 1. Recommended Topology

Use two process graphs:

- `ingest.bpg.yaml`: writes chunks/embeddings/metadata to the search store.
- `retrieve.bpg.yaml`: runs hybrid retrieval and returns ranked results.

Do not share runtime node instances between graphs. Share the datastore contract and provider config.

## 2. Shared Datastore Contract

Both graphs should import the same resource contract file and use a typed store key.

Example contract:

```yaml
types:
  SearchStoreRef:
    store: enum(search_main)
```

Each node that touches the datastore should include:

- `config.store: search_main`

This gives compile-time consistency across process files and prevents accidental store drift.

## 3. Weaviate-Based Design (Implemented Baseline)

Status: implemented baseline. These providers currently use a local shared JSONL store for runnable local examples while keeping Weaviate-oriented provider IDs and config contracts.

### Ingestion nodes

- `fs.markdown_list@v1` (`provider: fs.markdown_list`)
  - Input: path/glob config
  - Output: markdown documents with source metadata
- `text.markdown_chunk@v1` (`provider: text.markdown_chunk`)
  - Input: markdown documents
  - Output: chunked text with source offsets/ids
- `embed.text@v1` (`provider: embed.text`)
  - Input: chunk text
  - Output: vectors
- `weaviate.upsert@v1` (`provider: weaviate.upsert`)
  - Input: chunk text + vector + metadata
  - Output: upsert statistics

### Retrieval nodes

- `embed.text@v1` (`provider: embed.text`)
  - Input: query text
  - Output: query vector
- `weaviate.hybrid_search@v1` (`provider: weaviate.hybrid_search`)
  - Input: query text + vector + optional filters
  - Output: ranked hits (`bm25 + vector`)

Optional:

- `weaviate.delete@v1` (`provider: weaviate.delete`) for source re-index/delete flows.

## 4. Runtime Resolution

Resolve `search_main` in provider/env configuration to a single Weaviate deployment:

- `WEAVIATE_URL`
- `WEAVIATE_API_KEY` (if enabled)
- collection/class names for docs/chunks

Both processes must resolve `search_main` to the same endpoint and collection config.

## 5. Examples

See `examples/search/` for concrete ingestion/retrieval graph definitions and runnable workflow instructions.
