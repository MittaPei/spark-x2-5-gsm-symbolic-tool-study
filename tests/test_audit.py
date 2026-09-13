from spark_math_eval.audit import pair_transition


def test_pair_transition_names_the_policy_condition() -> None:
    assert pair_transition({"correct": True}, {"correct": False}) == (
        "direct_policy_only_correct"
    )
    assert pair_transition({"correct": False}, {"correct": True}) == (
        "calculator_policy_only_correct"
    )
