"""Orchestrator utilities for PaperIgnition v2"""

import json
import logging
from pathlib import Path
from typing import List

from core.models import DocSet

logger = logging.getLogger(__name__)


def load_docsets_from_json(json_dir: str) -> List[DocSet]:
    """Load DocSet objects from JSON files in a directory."""
    docsets = []
    json_path = Path(json_dir)
    if not json_path.exists():
        return docsets
    for json_file in sorted(json_path.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            docsets.append(DocSet(**data))
        except Exception as e:
            logger.warning(f"Failed to load {json_file}: {e}")
    return docsets


def save_docset_to_json(docset: DocSet, json_dir: str) -> str:
    """Save a DocSet object to a JSON file."""
    json_path = Path(json_dir)
    json_path.mkdir(parents=True, exist_ok=True)
    safe_id = docset.doc_id.replace("/", "_")
    filepath = json_path / f"{safe_id}.json"
    filepath.write_text(docset.model_dump_json(indent=2), encoding="utf-8")
    return str(filepath)
