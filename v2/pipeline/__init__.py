"""v2 pipeline — end-to-end orchestration (data through execution).

Public API for the scanner→agent bridge:
  * ``run_pipeline`` (orchestrator.py)  — compose run_scan + run_hedge_fund
  * ``PipelineResult``                  — orchestrator return type
  * ``TEMPLATES`` / ``DEFAULT_TEMPLATE`` — named analyst rosters
  * ``resolve_analysts``                — template + custom → analyst-key list
"""

from v2.pipeline.orchestrator import PipelineResult, run_pipeline
from v2.pipeline.templates import (
    DEFAULT_TEMPLATE,
    TEMPLATES,
    resolve_analysts,
)

__all__ = [
    "DEFAULT_TEMPLATE",
    "PipelineResult",
    "TEMPLATES",
    "resolve_analysts",
    "run_pipeline",
]
