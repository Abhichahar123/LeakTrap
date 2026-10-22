"""Domain and email-address normalization shared across the API."""

import re

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def normalize_domain(value: str) -> str:
    """Return a lowercase ASCII (punycode) domain, or raise ValueError.

    Accepts bare hostnames such as "Example.COM." or "bücher.de". Rejects URLs,
    ports, credentials, single labels and IP addresses.
    """
    domain = value.strip().lower().rstrip(".")
    if not domain:
        raise ValueError("domain must not be empty")
    if any(ch in domain for ch in "/:@?# \t"):
        raise ValueError(
            "enter a bare domain such as example.com, without scheme, path, port or spaces"
        )
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("domain is not a valid domain name") from None
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2:
        raise ValueError("domain must be a full domain name such as example.com")
    if not all(_LABEL.match(label) for label in labels):
        raise ValueError("domain contains an invalid label")
    if labels[-1].isdigit():
        raise ValueError("IP addresses are not accepted as domains")
    return domain


# Dot-atom local part (RFC 5322) without quoted strings or comments.
_LOCAL_PART = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")


def normalize_email(value: str) -> str:
    """Return a lowercase address "local@domain", or raise ValueError.

    Accepts only a bare address, not "Name <address>" forms.
    """
    address = value.strip().lower()
    if address.count("@") != 1:
        raise ValueError("must be a single email address such as name@example.com")
    local, domain = address.split("@")
    if not local or len(local) > 64 or not _LOCAL_PART.match(local):
        raise ValueError("email address has an invalid local part")
    address = f"{local}@{normalize_domain(domain)}"
    if len(address) > 320:
        raise ValueError("email address is too long")
    return address


def parent_domains(domain: str) -> list[str]:
    """The domain and each parent with at least two labels, most specific first.

    "mail.shop.example.com" -> ["mail.shop.example.com", "shop.example.com", "example.com"]
    """
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]
