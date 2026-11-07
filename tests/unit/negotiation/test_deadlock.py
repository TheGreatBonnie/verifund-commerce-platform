from commerce_core.negotiation.deadlock import detect_deadlock


def test_deadlock_continue_and_terminate():
    assert detect_deadlock(round=1, max_rounds=3, has_feasible_move=True, has_non_price_alternative=True).outcome == "continue"
    assert detect_deadlock(round=3, max_rounds=3, has_feasible_move=False, has_non_price_alternative=False).outcome == "terminate"
    assert detect_deadlock(round=2, max_rounds=3, has_feasible_move=False, has_non_price_alternative=True).outcome == "propose_alternative"
    assert detect_deadlock(round=1, max_rounds=3, has_feasible_move=True, has_non_price_alternative=False, expired=True).outcome == "terminate"
