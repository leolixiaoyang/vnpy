from dataclasses import asdict, dataclass


class DataError(ValueError):
    """A contract or accounting error; never silently downgraded."""


class ApproximationError(DataError):
    pass


@dataclass(frozen=True)
class QualityEvent:
    code: str
    detail: str


class QualityLog:
    def __init__(self, strict: bool = False):
        self.strict = strict
        self.events: list[QualityEvent] = []
        self._seen: set[tuple[str, str]] = set()

    def record(self, code: str, detail: str):
        if self.strict:
            raise ApproximationError(f"{code}: {detail}")
        key = (code, detail)
        if key not in self._seen:
            self._seen.add(key)
            self.events.append(QualityEvent(*key))

    def export(self):
        return [asdict(e) for e in self.events]
