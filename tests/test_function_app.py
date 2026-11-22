import function_app

# Azure's get_functions() may only be called once per app (a second call reports a duplicate name).
FUNCTIONS = {f.get_function_name(): f for f in function_app.app.get_functions()}
FUNCTION = FUNCTIONS["daily_digest"]
TIMER = next(
    b for b in FUNCTION.get_bindings() if b.type == "timerTrigger"
).get_dict_repr()
PAGE = next(
    b for b in FUNCTIONS["cleanup_page"].get_bindings() if b.type == "httpTrigger"
).get_dict_repr()


def test_there_are_two_functions_the_daily_timer_and_the_clean_up_page():
    assert set(FUNCTIONS) == {"daily_digest", "cleanup_page"}
    assert TIMER["type"] == "timerTrigger"


def test_the_clean_up_page_answers_get_and_post_at_api_cleanup():
    assert PAGE["route"] == "cleanup"
    assert sorted(str(getattr(m, "value", m)).lower() for m in PAGE["methods"]) == [
        "get",
        "post",
    ]
    # Anonymous at the Azure level on purpose: the signed link is the authentication.
    assert str(PAGE["authLevel"]).lower().endswith("anonymous")


def test_it_runs_at_0030_utc_which_is_6am_in_india():
    # NCRONTAB: seconds minutes hours day month weekday, in UTC
    assert TIMER["schedule"] == "0 30 0 * * *"


def test_a_restart_or_a_missed_run_never_triggers_a_catch_up():
    assert TIMER["runOnStartup"] is False
    assert TIMER["useMonitor"] is False


def test_our_logs_are_switched_on_so_python_does_not_drop_them():
    import logging

    assert logging.getLogger("gmail_agent").level == logging.INFO


def test_http_libraries_are_quiet_so_the_logs_hold_our_stage_lines_not_every_request():
    import logging

    # They log every request at INFO ("HTTP Request: POST <url> 200 OK"): harmless but noisy.
    for name in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        assert logging.getLogger(name).level == logging.WARNING, name
    assert logging.getLogger("gmail_agent").level == logging.INFO  # ours stay on
