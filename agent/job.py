"""The scheduled job: what the Azure Function's timer calls.

Settings come from the environment (app settings in Azure):
  DRY_RUN        must be exactly "false" (any case, spaces ignored) to change or send anything;
                 anything else, or unset, is a dry run that only builds and logs the plan.
  KEEP_IN_INBOX  "false" moves labelled mail out of the inbox; otherwise labels are only added.
  DIGEST_HOURS   how many hours back the digest looks (default 24).

Logs carry counts and the mode only: never a subject, a sender or any email text. If any step of the
run failed the job raises, so Azure marks the execution failed and its alert can fire.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from langchain_core.runnables import Runnable

from agent.daily import DailyResult, execute_daily, prepare_daily
from agent.digest_config import DigestConfig
from agent.schemas import Category

log = logging.getLogger("gmail_agent.job")


@dataclass
class Dependencies:
    """Everything the run needs, built once from the environment."""

    gmail: Any
    sheets: Any  # None when no Sheet is configured: bills are then skipped
    rules: dict[str, Category]
    config: DigestConfig
    classifier: Runnable
    extractor: Runnable
    summarizer: Runnable
    group_summarizer: Runnable


class JobFailedError(RuntimeError):
    """One or more steps of the daily run failed (the message lists step names and error types)."""


def _hours(env: Mapping[str, str]) -> float:
    raw = env.get("DIGEST_HOURS", "24")
    try:
        hours = float(raw)
    except ValueError:
        raise ValueError("DIGEST_HOURS must be a number of hours") from None
    if hours <= 0:
        raise ValueError("DIGEST_HOURS must be greater than zero")
    return hours


def run_scheduled(
    env: Mapping[str, str],
    now: datetime,
    build_dependencies: Callable[[Mapping[str, str]], Dependencies],
) -> DailyResult:
    apply = env.get("DRY_RUN", "true").strip().lower() == "false"
    keep_in_inbox = env.get("KEEP_IN_INBOX", "true").strip().lower() != "false"
    hours = _hours(env)

    deps = build_dependencies(env)
    plan = prepare_daily(
        deps.gmail,
        deps.rules,
        deps.config,
        deps.classifier,
        deps.extractor,
        deps.summarizer,
        deps.group_summarizer,
        since=now - timedelta(hours=hours),
        until=now,
        keep_in_inbox=keep_in_inbox,
    )
    log.info(
        "daily plan: %d mails in the last %g hours, %d to label, %d bill rows, dry_run=%s",
        plan.content.total,
        hours,
        plan.planned_labels,
        plan.planned_rows,
        not apply,
    )
    if not apply:
        log.info("dry run: nothing was changed or sent")
        return DailyResult(plan=plan)

    result = execute_daily(plan, deps.gmail, deps.sheets)
    log.info(
        "daily run done: %d rows added, %d mails labelled, digest sent=%s, %d problems",
        len(result.rows_added),
        len(result.labelled.moved) if result.labelled else 0,
        result.digest_message_id is not None,
        len(result.errors),
    )
    if result.errors:
        raise JobFailedError("daily run had problems: " + ", ".join(result.errors))
    return result
