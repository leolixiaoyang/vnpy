import hashlib
import json
from pathlib import Path

import pandas as pd

from ..quality import DataError, QualityLog
from .normalization import VERSION


class DataBundle:
    """A frozen normalized snapshot; loading never constructs an online client."""
    def __init__(self, tables=None, metadata=None):
        self.tables = {k: v.copy() for k, v in (tables or {}).items()}
        self.metadata = dict(metadata or {})

    def table(self, name):
        return self.tables.get(name, pd.DataFrame()).copy()

    def save(self, directory):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        files = {}
        for name, frame in sorted(self.tables.items()):
            target = path / f"{name}.parquet"
            frame.to_parquet(target, index=False)
            files[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest = {"normalization": VERSION, "metadata": self.metadata, "files": files}
        encoded = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
        manifest["snapshot_id"] = hashlib.sha256(encoded.encode()).hexdigest()
        (path / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return manifest

    @classmethod
    def load(cls, directory):
        path = Path(directory)
        manifest = json.loads((path / "manifest.json").read_text())
        if manifest["normalization"] != VERSION:
            raise DataError("Unsupported snapshot normalization version")
        check = {k: v for k, v in manifest.items() if k != "snapshot_id"}
        digest = hashlib.sha256(json.dumps(check, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if digest != manifest["snapshot_id"]:
            raise DataError("Snapshot manifest checksum mismatch")
        tables = {}
        for file, expected in manifest["files"].items():
            if Path(file).name != file or not file.endswith(".parquet"):
                raise DataError("Invalid snapshot member")
            target = path / file
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise DataError(f"Snapshot checksum mismatch: {file}")
            tables[Path(file).stem] = pd.read_parquet(target)
        return cls(tables, {**manifest["metadata"], "snapshot_id": manifest["snapshot_id"]})

    def preflight(self, start, end, quality: QualityLog):
        problems = []
        cal = self.table("trade_cal")
        if cal.empty or not {"cal_date", "is_open"} <= set(cal):
            problems.append("trade_cal with cal_date/is_open is required")
        else:
            sessions = cal[cal.is_open == 1].cal_date.sort_values().unique()
            if not any(start <= d <= end for d in sessions):
                problems.append("No trading sessions in requested interval")
            if sum(d < start for d in sessions) < 10:
                quality.record("short_warmup", "Fewer than ten prior trading sessions")
            if cal.cal_date.min() > start or cal.cal_date.max() < end:
                quality.record("calendar_coverage", f"Requested {start}..{end}; calendar does not cover endpoints")
        if all(self.table(n).empty for n in ["daily", "fund_daily"]):
            problems.append("At least one tradable price dataset is required")
        if problems:
            raise DataError("Preflight failed: " + "; ".join(problems))
        for event in self.metadata.get("quality", []):
            quality.record(event["code"], event["detail"])
