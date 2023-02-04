from typing import List, Sequence


def plural(word: str, obj: Sequence | List | float) -> str:
    if isinstance(obj, List):
        return f"{word}{'s' * (len(obj) != 1)}"
    return f"{word}{'s' * (obj not in [0, 1])}"
