"""Small shared helpers: ORM->dict projection, model cost estimate, upload directory."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def as_dict(model: Any, fields: list[str]) -> dict[str, Any]:
    return {field: getattr(model, field) for field in fields}


def estimated_model_cost(input_tokens: int, output_tokens: int) -> float:
    input_rate = float(os.getenv("MODEL_INPUT_COST_PER_MILLION", "0"))
    output_rate = float(os.getenv("MODEL_OUTPUT_COST_PER_MILLION", "0"))
    return round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 8)
