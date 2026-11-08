"""Azure Functions entry point (Python v2 programming model): one timer, 6:00 AM IST.

All the work is in agent.job.run_scheduled (tested); this file only schedules it.
The schedule is an NCRONTAB expression in UTC: "0 30 0 * * *" = 00:30 UTC = 06:00 IST, every day.
run_on_startup and use_monitor are off on purpose: a restart or a missed run must never trigger a
catch-up, because a catch-up could send the digest twice.
"""

import os
from datetime import UTC, datetime

import azure.functions as func

from agent.job import run_scheduled
from agent.runtime import build_dependencies

app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 30 0 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=False,
)
def daily_digest(timer: func.TimerRequest) -> None:
    run_scheduled(os.environ, datetime.now(UTC), build_dependencies)
