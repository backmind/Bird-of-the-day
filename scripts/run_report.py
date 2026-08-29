"""Run summary: visible degradation without failing the job.

The generator never hard-fails on degraded content (that principle keeps
the site publishing through outages), which historically made failures
invisible: the cron job was green while entries silently lost their
enriched text or map. This module gives every run a summary that lands
in the logs always, and in GitHub Actions annotations plus the step
summary when running in CI.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def info(self, text: str) -> None:
        self.lines.append(text)

    def warn(self, text: str) -> None:
        self.lines.append(f"WARNING: {text}")
        self.warnings.append(text)

    @property
    def degraded(self) -> bool:
        return bool(self.warnings)

    def emit(self) -> None:
        if self.lines:
            logger.info(
                "RUN SUMMARY:\n%s",
                "\n".join(f"  - {line}" for line in self.lines),
            )
        if os.environ.get("GITHUB_ACTIONS") != "true":
            return
        for warning in self.warnings:
            print(f"::warning::{warning}")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            try:
                with open(summary_path, "a", encoding="utf-8") as fh:
                    fh.write("## Bird of the Day run\n\n")
                    for line in self.lines:
                        fh.write(f"- {line}\n")
                    fh.write("\n")
            except OSError:
                logger.warning("Could not write GITHUB_STEP_SUMMARY")
