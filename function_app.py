"""Azure Functions entry point (Python v2 programming model): the 6:00 AM IST timer, and the
clean-up approval page behind the digest's button.

All the work is in agent.job.run_scheduled and agent.approval_http.serve (tested); this file only
wires them to their triggers.
The schedule is an NCRONTAB expression in UTC: "0 30 0 * * *" = 00:30 UTC = 06:00 IST, every day.
run_on_startup and use_monitor are off on purpose: a restart or a missed run must never trigger a
catch-up, because a catch-up could send the digest twice.
"""

import logging
import os
from datetime import UTC, datetime

import azure.functions as func

from agent.approval_http import serve
from agent.job import run_scheduled
from agent.runtime import build_approval_runtime, build_dependencies

# Python drops INFO records by default; without this our counts-and-stages log lines never exist.
logging.getLogger("gmail_agent").setLevel(logging.INFO)
# The HTTP libraries log every request at INFO (URL and status only): quiet them so the log holds
# our stage lines. httpx2/httpcore2 are the names the installed OpenAI client actually uses.
for _noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 30 0 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=False,
)
def daily_digest(timer: func.TimerRequest) -> None:
    run_scheduled(os.environ, datetime.now(UTC), build_dependencies)


# Anonymous at the Azure level on purpose: the signed link in the digest is the authentication, and
# agent.approval_http checks it (plus the CLEANUP_ENABLED switch) before anything is built.
@app.route(
    route="cleanup", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS
)
def cleanup_page(req: func.HttpRequest) -> func.HttpResponse:
    response = serve(
        req.method,
        dict(req.params),
        req.get_body(),
        os.environ,
        datetime.now(UTC),
        build_approval_runtime,
    )
    return func.HttpResponse(
        response.body, status_code=response.status, headers=response.headers
    )
