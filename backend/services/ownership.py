"""Ownership filter for user-facing queries.

Every user-facing read and write is limited to the authenticated user's own
rows. A missing user id is a programming error, never "records without an
owner": unowned historical records are visible to nobody.
"""


def owned_by(column, user_id: int):
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
        raise ValueError("an authenticated user id is required")
    return column == user_id
