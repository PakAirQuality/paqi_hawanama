"""CLI: pull flagged traces from Langfuse → regression_cases.json.

Usage:
    cd apps/api
    python -m tests.bench.langfuse_sync

Requires env vars: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REGRESSION_PATH = Path(__file__).parent / "fixtures" / "regression_cases.json"
DATASET_NAME = "copilot-regression"


def sync() -> None:
    try:
        from langfuse import Langfuse
    except ImportError:
        print("ERROR: langfuse package not installed. Run: pip install langfuse>=2.0")
        sys.exit(1)

    client = Langfuse()

    # Fetch the dataset
    try:
        dataset = client.get_dataset(DATASET_NAME)
    except Exception as e:
        print(f"ERROR: Could not fetch dataset '{DATASET_NAME}': {e}")
        print("Create it in Langfuse UI first, then add items with the expected format.")
        sys.exit(1)

    items = dataset.items
    if not items:
        print(f"No items in dataset '{DATASET_NAME}'. Nothing to sync.")
        return

    # Load existing regression cases
    existing = json.loads(REGRESSION_PATH.read_text())
    existing_ids = {c["id"] for c in existing.get("cases", [])}

    added = 0
    for item in items:
        # Expected item format:
        # input: {"user_message": "...", "session": {"current_date": "..."}}
        # expected_output: {"expect_tool": "...", "expect_args": {...}, "assertions": {...}}
        # metadata: {"id": "...", "category": "...", "description": "...", "mock_output_key": "..."}
        meta = item.metadata or {}
        case_id = meta.get("id") or item.id

        if case_id in existing_ids:
            continue

        inp = item.input or {}
        expected = item.expected_output or {}

        case = {
            "id": case_id,
            "category": meta.get("category", "regression"),
            "description": meta.get("description", f"Langfuse import: {case_id}"),
            "session": inp.get("session", {"current_date": "2026-03-06"}),
            "turns": [
                {
                    "user_message": inp.get("user_message", inp.get("message", "")),
                    "expect_tool": expected.get("expect_tool"),
                    "expect_args": expected.get("expect_args"),
                    "mock_output_key": meta.get("mock_output_key", ""),
                    "assertions": expected.get("assertions", {}),
                }
            ],
        }

        existing["cases"].append(case)
        existing_ids.add(case_id)
        added += 1

    REGRESSION_PATH.write_text(json.dumps(existing, indent=2) + "\n")
    print(f"Synced {added} new cases from Langfuse ({len(existing['cases'])} total in regression_cases.json)")


if __name__ == "__main__":
    sync()
