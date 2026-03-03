from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples" / "search"


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} must parse to a YAML object."
    return data


def test_search_examples_exist_and_parse() -> None:
    shared = EXAMPLES_DIR / "search-resources.bpg.yaml"
    ingest = EXAMPLES_DIR / "ingest.bpg.yaml"
    retrieve = EXAMPLES_DIR / "retrieve.bpg.yaml"

    for file_path in (shared, ingest, retrieve):
        assert file_path.exists(), f"Missing example file: {file_path}"
        _load_yaml(file_path)


def test_search_examples_share_store_identifier() -> None:
    ingest = _load_yaml(EXAMPLES_DIR / "ingest.bpg.yaml")
    retrieve = _load_yaml(EXAMPLES_DIR / "retrieve.bpg.yaml")

    ingest_store = ingest["nodes"]["write_weaviate"]["config"]["store"]
    retrieve_store = retrieve["nodes"]["search"]["config"]["store"]
    assert ingest_store == "search_main"
    assert retrieve_store == "search_main"
