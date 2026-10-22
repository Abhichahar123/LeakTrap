"""Curated canary nicknames and scope-aware selection.

A nickname is a canary marker: if it later appears in a message, it hints at
which signup the sender's data came from. It is evidence to weigh, never proof
on its own that a particular company leaked data.

Uniqueness mirrors the database index uq_signups_user_id_nickname_lower:
case-insensitive within one owner (user_id), with all signups that have no
user sharing a single scope.
"""

import secrets
from collections.abc import Callable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import Signup

# Distinctive single words, avoiding greetings, titles and common first names.
NICKNAMES: tuple[str, ...] = (
    "Albatross", "Alder", "Antares", "Aster", "Basilisk", "Borealis", "Bramble",
    "Calypso", "Caracal", "Cassowary", "Cinder", "Cobalt", "Comet", "Cormorant",
    "Corvid", "Cygnus", "Dervish", "Drumlin", "Dunlin", "Eclipse", "Ember",
    "Equinox", "Falcon", "Fennec", "Firefly", "Fjord", "Galleon", "Garnet",
    "Gossamer", "Gryphon", "Halcyon", "Harrier", "Heron", "Ibex", "Indigo",
    "Jacaranda", "Juniper", "Kestrel", "Kingfisher", "Kittiwake", "Kraken",
    "Larkspur", "Lodestar", "Lynx", "Magnolia", "Marlin", "Meridian", "Mistral",
    "Monsoon", "Moraine", "Narwhal", "Nautilus", "Nebula", "Nightjar", "Nimbus",
    "Obsidian", "Ocelot", "Onyx", "Opal", "Oriole", "Orion", "Osprey", "Pangolin",
    "Pelican", "Peregrine", "Phoenix", "Plover", "Puffin", "Pulsar", "Quartz",
    "Quasar", "Quokka", "Rook", "Sable", "Saffron", "Sandpiper", "Sequoia",
    "Sirocco", "Solstice", "Starling", "Tamarind", "Tamarisk", "Tanager",
    "Thistle", "Topaz", "Tundra", "Umbra", "Verbena", "Vesper", "Vireo",
    "Wapiti", "Whimbrel", "Wolverine", "Wren", "Xylem", "Yarrow", "Zenith",
    "Zephyr", "Zircon",
)


class NicknameExhaustedError(Exception):
    """Every curated nickname is already used in the requested scope."""


def normalize_nickname(nickname: str) -> str:
    """Comparison form. Matches lower() in the database index."""
    return nickname.strip().lower()


def choose_nickname(
    used_in_scope: set[str],
    used_anywhere: set[str] = frozenset(),
    pool: Sequence[str] | None = None,
    choice: Callable[[Sequence[str]], str] = secrets.choice,
) -> str:
    """Pick a nickname not used in the owner's scope.

    Nicknames no other owner uses are preferred so markers stay as distinctive
    as possible; a nickname used by another owner is only chosen once those
    run out. Arguments must hold normalized values.
    """
    pool = NICKNAMES if pool is None else pool
    available = [n for n in pool if normalize_nickname(n) not in used_in_scope]
    if not available:
        raise NicknameExhaustedError(
            f"All {len(pool)} curated nicknames are already used in this ownership scope"
        )
    unused_elsewhere = [n for n in available if normalize_nickname(n) not in used_anywhere]
    return choice(unused_elsewhere or available)


def used_nicknames(session: Session, user_id: int | None) -> set[str]:
    """Normalized nicknames already used in the given owner's scope."""
    owner = Signup.user_id.is_(None) if user_id is None else Signup.user_id == user_id
    query = select(func.lower(Signup.nickname)).where(Signup.nickname.is_not(None), owner)
    return set(session.scalars(query))


def used_nicknames_any_owner(session: Session) -> set[str]:
    query = select(func.lower(Signup.nickname)).where(Signup.nickname.is_not(None)).distinct()
    return set(session.scalars(query))
