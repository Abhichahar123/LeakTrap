"""Email alias generation for signups.

Aliases look like PREFIX.SUFFIX@DOMAIN (or SUFFIX@DOMAIN without a prefix),
where SUFFIX is random lowercase letters and digits from the secrets module.
A generated alias is only a string: this module does not configure mail
routing, and nothing here means the address has been verified or can receive
mail.
"""

import re
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models import Signup
from backend.services.domains import normalize_domain

SUFFIX_ALPHABET = string.ascii_lowercase + string.digits
_PREFIX = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_ALIAS = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*@[a-z0-9.-]+$")


class AliasConfigurationError(Exception):
    """Alias generation was requested but the configuration is missing or invalid."""


class AliasGenerationError(Exception):
    """No unused alias was found within the retry limit."""


@dataclass(frozen=True)
class AliasConfig:
    domain: str | None
    prefix: str = ""
    suffix_length: int = 8
    max_retries: int = 5

    @classmethod
    def from_settings(cls, settings: Settings) -> "AliasConfig":
        return cls(
            domain=settings.alias_domain,
            prefix=settings.alias_prefix,
            suffix_length=settings.alias_suffix_length,
            max_retries=settings.marker_max_retries,
        )

    def validated(self) -> "AliasConfig":
        """Return a normalized copy, or raise AliasConfigurationError."""
        if not self.domain:
            raise AliasConfigurationError(
                "Alias generation needs LEAKTRACE_ALIAS_DOMAIN to be configured. "
                "Set it, or create the signup with generate_alias=false."
            )
        try:
            domain = normalize_domain(self.domain)
        except ValueError as exc:
            raise AliasConfigurationError(f"LEAKTRACE_ALIAS_DOMAIN is invalid: {exc}") from None
        prefix = self.prefix.strip().lower()
        if prefix and (len(prefix) > 40 or not _PREFIX.match(prefix)):
            raise AliasConfigurationError(
                "LEAKTRACE_ALIAS_PREFIX may only contain lowercase letters, digits and "
                "single '.', '_' or '-' separators, up to 40 characters."
            )
        if not 4 <= self.suffix_length <= 16:
            raise AliasConfigurationError("LEAKTRACE_ALIAS_SUFFIX_LENGTH must be between 4 and 16.")
        if not 1 <= self.max_retries <= 20:
            raise AliasConfigurationError("LEAKTRACE_MARKER_MAX_RETRIES must be between 1 and 20.")
        return AliasConfig(domain, prefix, self.suffix_length, self.max_retries)


def normalize_alias(address: str) -> str:
    """Lowercase and trim an alias; raise ValueError if it is not alias-shaped."""
    alias = address.strip().lower()
    if len(alias) > 320 or not _ALIAS.match(alias) or len(alias.split("@")[0]) > 64:
        raise ValueError(f"not a valid alias: {address!r}")
    return alias


def random_suffix(length: int) -> str:
    return "".join(secrets.choice(SUFFIX_ALPHABET) for _ in range(length))


def build_alias(config: AliasConfig, suffix: str) -> str:
    local = f"{config.prefix}.{suffix}" if config.prefix else suffix
    return normalize_alias(f"{local}@{config.domain}")


def generate_alias(config: AliasConfig, is_taken: Callable[[str], bool]) -> str:
    """Return an alias that is_taken() reports as free.

    This check reduces collisions but cannot prevent races; the unique index
    uq_signups_alias_lower remains the final authority when the row is saved.
    """
    config = config.validated()
    for _ in range(config.max_retries):
        candidate = build_alias(config, random_suffix(config.suffix_length))
        if not is_taken(candidate):
            return candidate
    raise AliasGenerationError(
        f"Could not find an unused alias after {config.max_retries} attempts"
    )


def alias_exists(session: Session, alias: str) -> bool:
    return bool(session.scalar(select(exists().where(func.lower(Signup.alias) == alias))))
