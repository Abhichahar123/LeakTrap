import re

import pytest

from backend.services.nickname_generator import (
    NICKNAMES,
    NicknameExhaustedError,
    choose_nickname,
    normalize_nickname,
)

GENERIC_WORDS = {"sir", "madam", "boss", "dear", "friend", "user", "customer", "client", "buddy"}


def test_list_has_at_least_50_nicknames() -> None:
    assert len(NICKNAMES) >= 50


def test_no_duplicates_after_normalization() -> None:
    assert len({normalize_nickname(n) for n in NICKNAMES}) == len(NICKNAMES)


def test_format_is_single_capitalized_word() -> None:
    for nickname in NICKNAMES:
        assert re.fullmatch(r"[A-Z][a-z]{2,19}", nickname), nickname


def test_no_generic_greetings_or_titles() -> None:
    assert not GENERIC_WORDS & {normalize_nickname(n) for n in NICKNAMES}


def test_normalization_is_case_and_whitespace_insensitive() -> None:
    assert normalize_nickname("  ZePHyr ") == normalize_nickname("zephyr") == "zephyr"


def test_chosen_nickname_comes_from_pool() -> None:
    assert choose_nickname(set()) in NICKNAMES


def test_used_nicknames_are_never_reused() -> None:
    pool = ["Falcon", "Zephyr", "Quasar"]
    used: set[str] = set()
    for _ in pool:
        chosen = choose_nickname(used, pool=pool)
        assert normalize_nickname(chosen) not in used
        used.add(normalize_nickname(chosen))
    assert used == {"falcon", "zephyr", "quasar"}


def test_used_check_is_case_insensitive() -> None:
    assert choose_nickname({"falcon"}, pool=["Falcon", "Zephyr"]) == "Zephyr"


def test_prefers_nicknames_unused_by_other_owners() -> None:
    for _ in range(20):
        assert choose_nickname(set(), {"falcon"}, pool=["Falcon", "Zephyr"]) == "Zephyr"


def test_falls_back_to_nickname_used_by_other_owner() -> None:
    assert choose_nickname({"zephyr"}, {"falcon", "zephyr"}, pool=["Falcon", "Zephyr"]) == "Falcon"


def test_exhaustion_raises_instead_of_reusing() -> None:
    with pytest.raises(NicknameExhaustedError):
        choose_nickname({normalize_nickname(n) for n in NICKNAMES})


def test_uses_cryptographic_choice_by_default() -> None:
    import secrets

    assert choose_nickname.__defaults__[-1] is secrets.choice
