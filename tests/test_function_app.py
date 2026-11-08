import function_app

# Azure's get_functions() may only be called once per app (a second call reports a duplicate name).
(FUNCTION,) = function_app.app.get_functions()
TIMER = next(
    b for b in FUNCTION.get_bindings() if b.type == "timerTrigger"
).get_dict_repr()


def test_there_is_exactly_one_function_a_daily_timer():
    assert FUNCTION.get_function_name() == "daily_digest"
    assert TIMER["type"] == "timerTrigger"


def test_it_runs_at_0030_utc_which_is_6am_in_india():
    # NCRONTAB: seconds minutes hours day month weekday, in UTC
    assert TIMER["schedule"] == "0 30 0 * * *"


def test_a_restart_or_a_missed_run_never_triggers_a_catch_up():
    assert TIMER["runOnStartup"] is False
    assert TIMER["useMonitor"] is False
