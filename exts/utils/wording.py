from collections.abc import Sequence


def plural(word: str, obj: Sequence | list | float) -> str:
    if isinstance(obj, list):
        return f"{word}{'s' * (len(obj) != 1)}"
    return f"{word}{'s' * (obj not in [0, 1])}"
