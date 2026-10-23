import re

import pytest

from backend.config import get_settings
from backend.services import alias_generator
from backend.services.alias_generator import (
    AliasConfig,
    AliasConfigurationError,
    AliasGenerationError,
    build_alias,
    generate_alias,
    normalize_alias,
    random_suffix,
)
from backend.services.domains import normalize_domain

CONFIG = AliasConfig(domain="Aliases.Example.COM", prefix="Test", suffix_length=4, max_retries=5)


def never_taken(alias: str) -> bool:
    return False


def test_alias_uses_configured_domain_and_prefix() -> None:
    alias = generate_alias(CONFIG, never_taken)
    assert re.fullmatch(r"test\.[a-z0-9]{4}@aliases\.example\.com", alias)


def test_alias_without_prefix() -> None:
    alias = generate_alias(AliasConfig(domain="example.org"), never_taken)
    assert re.fullmatch(r"[a-z0-9]{8}@example\.org", alias)  # default length is 8


def test_suffix_length_is_configurable() -> None:
    alias = generate_alias(AliasConfig(domain="example.org", suffix_length=8), never_taken)
    assert re.fullmatch(r"[a-z0-9]{8}@example\.org", alias)


def test_random_suffix_alphabet() -> None:
    suffixes = {random_suffix(4) for _ in range(200)}
    assert all(re.fullmatch(r"[a-z0-9]{4}", s) for s in suffixes)
    assert len(suffixes) > 150  # random, not constant


def test_normalization() -> None:
    assert normalize_alias("  Test.AbC1@Example.COM ") == "test.abc1@example.com"
    for bad in ("no-at-sign", "a@@b.com", "a b@c.com", ".x@example.com"):
        with pytest.raises(ValueError):
            normalize_alias(bad)


def test_build_alias_normalizes() -> None:
    config = CONFIG.validated()
    assert build_alias(config, "ab12") == "test.ab12@aliases.example.com"


def test_collision_retries_until_free(monkeypatch) -> None:
    suffixes = iter(["aaaa", "bbbb", "cccc"])
    monkeypatch.setattr(alias_generator, "random_suffix", lambda n: next(suffixes))
    taken = {"test.aaaa@aliases.example.com", "test.bbbb@aliases.example.com"}
    checked: list[str] = []

    def is_taken(alias: str) -> bool:
        checked.append(alias)
        return alias in taken

    assert generate_alias(CONFIG, is_taken) == "test.cccc@aliases.example.com"
    assert len(checked) == 3


def test_retry_exhaustion_raises_controlled_error() -> None:
    calls = []

    def always_taken(alias: str) -> bool:
        calls.append(alias)
        return True

    with pytest.raises(AliasGenerationError):
        generate_alias(CONFIG, always_taken)
    assert len(calls) == CONFIG.max_retries


@pytest.mark.parametrize("domain", [None, ""])
def test_missing_domain_is_a_configuration_error(domain) -> None:
    with pytest.raises(AliasConfigurationError, match="LEAKTRACE_ALIAS_DOMAIN"):
        generate_alias(AliasConfig(domain=domain), never_taken)


@pytest.mark.parametrize(
    "config",
    [
        AliasConfig(domain="https://example.com"),
        AliasConfig(domain="localhost"),
        AliasConfig(domain="example.com", prefix="bad prefix"),
        AliasConfig(domain="example.com", suffix_length=2),
        AliasConfig(domain="example.com", max_retries=0),
    ],
)
def test_invalid_configuration_is_rejected(config: AliasConfig) -> None:
    with pytest.raises(AliasConfigurationError):
        config.validated()


def test_settings_have_no_hardcoded_domain(monkeypatch) -> None:
    monkeypatch.delenv("LEAKTRACE_ALIAS_DOMAIN", raising=False)
    config = AliasConfig.from_settings(get_settings())
    assert config.domain is None
    assert config.suffix_length == 8  # new aliases: 8 characters (existing aliases are unchanged)


def test_generator_makes_no_verification_claim() -> None:
    # A bare string: no delivery or verification state is attached or implied.
    assert type(generate_alias(CONFIG, never_taken)) is str


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Example.COM.", "example.com"), (" shop.example.co.uk ", "shop.example.co.uk"),
     ("bücher.de", "xn--bcher-kva.de")],
)
def test_normalize_domain(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "  ", "example", "http://example.com", "example.com/path", "example.com:443",
            "user@example.com", "-bad.com", "a..b.com", "127.0.0.1", "exa mple.com"],
)
def test_normalize_domain_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(raw)
