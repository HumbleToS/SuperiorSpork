from typing import SupportsAbs


class plural:
    def __init__(self, value: SupportsAbs[int]) -> None:
        self.value = value

    def __format__(self, format_spec: str) -> str:
        v = self.value
        singular, _, plural = format_spec.partition("|")
        plural = plural or f"{singular}s"
        if abs(v) != 1:
            return f"{v} {plural}"
        return f"{v} {singular}"
