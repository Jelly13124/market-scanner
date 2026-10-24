"""MissingData - deterministic. Walks ctx.prior for SectionPayload
with skipped=True; produces a 'Missing Data / Low Confidence' table."""

from __future__ import annotations

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext


class MissingDataSection(Section):
    name = "missing_data"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        rows = [
            "| Missing or skipped section | Reason | Impact | Fallback |",
            "|---|---|---|---|",
        ]
        any_skipped = False
        for name, payload in ctx.prior.items():
            if name.startswith("_"):
                continue
            if payload.skipped:
                any_skipped = True
                reason = payload.skip_reason or "n/a"
                rows.append(
                    f"| {name} | {reason} | (downstream sections cited "
                    "this as n/a where relevant) | (rendered as 'n/a' "
                    "block in HTML) |"
                )
        if not any_skipped:
            body = "\n\nAll sections completed successfully. No missing-data caveats.\n"
        else:
            body = "\n\n" + "\n".join(rows) + "\n"
        md = "## Missing Data / Low Confidence Areas" + body
        return SectionPayload(
            name=self.name, markdown=md,
            structured={"skipped_sections": [
                n for n, p in ctx.prior.items()
                if not n.startswith("_") and p.skipped
            ]},
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["missing_data"] = MissingDataSection()
