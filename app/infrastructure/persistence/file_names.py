from hashlib import sha256


def safe_storage_name(value: str) -> str:
    """Convert an external identifier into a safe, unique file name."""

    readable = "".join(
        character
        for character in value
        if character.isalnum()
        or character in {"-", "_"}
    )

    prefix = (readable or "anonymous")[:48]
    digest = sha256(
        value.encode("utf-8"),
    ).hexdigest()[:12]

    return f"{prefix}-{digest}"
