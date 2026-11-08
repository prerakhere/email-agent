import logging
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.runnables import RunnableLambda
from test_daily import EMAILS, FakeGmail, FakeSheets, Models, email

from agent.auth import SignInExpiredError
from agent.digest_config import DEFAULT_CONFIG
from agent.job import Dependencies, JobFailedError, run_scheduled

NOW = datetime(2026, 11, 9, 0, 30, tzinfo=UTC)  # 6:00 AM IST


class RecordingGmail(FakeGmail):
    def fetch_since(self, since, max_results=500):
        self.since = since
        return super().fetch_since(since, max_results)


def make_deps(gmail=None, sheets="default"):
    models = Models()
    return Dependencies(
        gmail=gmail or RecordingGmail(EMAILS),
        sheets=FakeSheets() if sheets == "default" else sheets,
        rules={},
        config=DEFAULT_CONFIG,
        classifier=models.classifier,
        extractor=models.extractor,
        summarizer=models.summarizer,
        group_summarizer=models.group,
        transaction_extractor=models.tx_extractor,
    )


def run(env, deps=None):
    deps = deps or make_deps()
    seen = []

    def build(received_env):
        seen.append(received_env)
        return deps

    result = run_scheduled(env, NOW, build)
    return result, deps, seen


def test_by_default_a_scheduled_run_is_a_dry_run_that_changes_nothing():
    result, deps, _ = run({})
    assert deps.gmail.added == [] and deps.gmail.sent == [] and deps.sheets.calls == []
    assert result.digest_message_id is None
    assert result.planned_labels == 3


def test_with_dry_run_false_it_logs_bills_labels_mail_and_sends_the_digest():
    result, deps, _ = run({"DRY_RUN": "false"})
    assert result.rows_added == ["2"]
    assert len(deps.gmail.added) == 3 and len(deps.gmail.sent) == 1
    assert result.digest_message_id == "sent-1" and result.errors == []


def test_dry_run_must_be_exactly_false_to_act():
    for value in ("0", "no", "False-ish", ""):
        _, deps, _ = run({"DRY_RUN": value})
        assert deps.gmail.sent == [], value
    _, deps, _ = run({"DRY_RUN": " FALSE "})
    assert len(deps.gmail.sent) == 1


def test_the_window_is_the_last_24_hours_by_default_and_configurable():
    _, deps, _ = run({})
    assert deps.gmail.since == NOW - timedelta(hours=24)
    _, deps, _ = run({"DIGEST_HOURS": "12"})
    assert deps.gmail.since == NOW - timedelta(hours=12)


def test_a_silly_window_setting_is_named_in_the_error():
    with pytest.raises(ValueError, match="DIGEST_HOURS"):
        run({"DIGEST_HOURS": "a day"})
    with pytest.raises(ValueError, match="DIGEST_HOURS"):
        run({"DIGEST_HOURS": "0"})


def test_mail_stays_in_the_inbox_unless_keep_in_inbox_is_false():
    _, deps, _ = run({"DRY_RUN": "false"})
    assert deps.gmail.moved == [] and len(deps.gmail.added) == 3
    _, deps, _ = run({"DRY_RUN": "false", "KEEP_IN_INBOX": "false"})
    assert deps.gmail.added == [] and sorted(i for i, _ in deps.gmail.moved) == [
        "2",
        "3",
    ]


def test_the_dependencies_are_built_once_from_the_environment():
    env = {"DRY_RUN": "false", "SOMETHING": "x"}
    _, _, seen = run(env)
    assert seen == [env]


def test_a_failed_step_makes_the_run_fail_after_the_others_finished():
    gmail = RecordingGmail(EMAILS)
    gmail.fail_send = True
    with pytest.raises(JobFailedError, match="send_digest: RuntimeError") as caught:
        run({"DRY_RUN": "false"}, make_deps(gmail=gmail))
    assert "private" not in str(caught.value)  # error text never leaks into the failure
    assert len(gmail.added) == 3  # the labels were still applied


def test_logs_carry_counts_and_never_email_text(caplog):
    with caplog.at_level(logging.INFO, logger="gmail_agent.job"):
        run({"DRY_RUN": "false"})
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "4" in logged and "dry_run=False" in logged  # counts and mode are there
    for secret in (
        "Interview next week",
        "Statement for October",
        "Weekly reading",
        "@x.com",
    ):
        assert secret not in logged


def test_without_a_sheets_client_the_run_still_works():
    result, deps, _ = run({"DRY_RUN": "false"}, make_deps(sheets=None))
    assert result.rows_added == [] and len(deps.gmail.sent) == 1


# ---- unexpected errors must never carry a library's message (it can contain secrets) ----

SECRET = "sk-super-secret-key-123"


def exploding_build(_env):
    raise RuntimeError(f"Illegal header value b'{SECRET}'")


def deps_with_failing_classifier():
    deps = make_deps()

    def boom(_request):
        raise RuntimeError(f"Illegal header value b'{SECRET}'")

    deps.classifier = RunnableLambda(boom)
    return deps


def test_an_unexpected_error_is_reported_by_type_only():
    with pytest.raises(JobFailedError, match="RuntimeError") as caught:
        run_scheduled({}, NOW, exploding_build)
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_an_error_while_reading_or_summarising_is_sanitised_too():
    deps = deps_with_failing_classifier()
    with pytest.raises(JobFailedError) as caught:
        run_scheduled({}, NOW, lambda _env: deps)
    assert "RuntimeError" in str(caught.value) and SECRET not in str(caught.value)


def test_the_log_records_the_error_type_but_not_its_message(caplog):
    with (
        caplog.at_level(logging.INFO, logger="gmail_agent.job"),
        pytest.raises(JobFailedError),
    ):
        run_scheduled({}, NOW, exploding_build)
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged and SECRET not in logged


def test_an_expired_google_sign_in_keeps_its_own_helpful_message():
    def expired(_env):
        raise SignInExpiredError("Google sign-in expired or was revoked: sign in again")

    with pytest.raises(SignInExpiredError, match="sign in again"):
        run_scheduled({}, NOW, expired)


def test_detailed_errors_can_be_switched_on_for_debugging():
    with pytest.raises(RuntimeError, match="Illegal header") as caught:
        run_scheduled({"DETAILED_ERRORS": "true"}, NOW, exploding_build)
    assert not isinstance(caught.value, JobFailedError)


def test_the_scheduled_run_passes_the_transaction_extractor_through():
    gmail = RecordingGmail([*EMAILS, email("5", "UPI txn alert")])
    deps = make_deps(gmail=gmail)
    result, _, _ = run({}, deps)
    spend = next(s for s in result.content.sections if s.title == "Transactions")
    assert spend.table is not None and len(spend.table.rows) == 1
