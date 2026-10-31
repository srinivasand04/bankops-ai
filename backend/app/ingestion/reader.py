"""Read a dataset folder and validate it: per-record schema checks plus cross-references."""

import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from app.ingestion.schemas import (
    ApplicationIn,
    ChangeIn,
    Dataset,
    DatasetManifest,
    DependencyIn,
    IncidentIn,
    OperationalEventIn,
)

FILES = {
    "applications": (ApplicationIn, True),
    "dependencies": (DependencyIn, False),
    "changes": (ChangeIn, False),
    "incidents": (IncidentIn, False),
    "operational_events": (OperationalEventIn, False),
}


class DatasetError(Exception):
    """Raised with every problem found, so a dataset can be fixed in one pass."""

    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} problem(s) in dataset:\n  - " + "\n  - ".join(errors))
        self.errors = errors


def _load_json(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path.name}: invalid JSON ({exc})")
        return None


def _validate_list(file: str, raw, model, errors: list[str]) -> list:
    if not isinstance(raw, list):
        errors.append(f"{file}: expected a JSON list")
        return []
    records = []
    for index, item in enumerate(raw):
        try:
            records.append(model.model_validate(item))
        except ValidationError as exc:
            for err in exc.errors():
                location = ".".join(str(p) for p in err["loc"])
                errors.append(f"{file}[{index}] {location}: {err['msg']}")
    return records


def _duplicates(values) -> list:
    return sorted(v for v, n in Counter(values).items() if n > 1 and v is not None)


def check_references(ds: Dataset) -> list[str]:
    errors: list[str] = []
    app_codes = {a.code for a in ds.applications}
    change_refs = {c.change_reference for c in ds.changes}

    for label, values in (
        ("application code", [a.code for a in ds.applications]),
        ("application name", [a.name for a in ds.applications]),
        ("change_reference", [c.change_reference for c in ds.changes]),
        ("incident reference", [i.reference for i in ds.incidents]),
        ("incident external_id", [i.external_id for i in ds.incidents]),
    ):
        if dupes := _duplicates(values):
            errors.append(f"duplicate {label}: {', '.join(dupes)}")

    def need_app(where: str, code: str):
        if code not in app_codes:
            errors.append(f"{where}: unknown application '{code}'")

    for i, d in enumerate(ds.dependencies):
        need_app(f"dependencies[{i}]", d.application)
        need_app(f"dependencies[{i}]", d.depends_on)
        if d.application == d.depends_on:
            errors.append(f"dependencies[{i}]: an application cannot depend on itself")
    for i, c in enumerate(ds.changes):
        need_app(f"changes[{i}]", c.application)
    for i, e in enumerate(ds.operational_events):
        need_app(f"operational_events[{i}]", e.application)
    for i, inc in enumerate(ds.incidents):
        need_app(f"incidents[{i}]", inc.application)
        for link in inc.change_links:
            if link.change_reference not in change_refs:
                errors.append(f"incidents[{i}]: unknown change '{link.change_reference}'")
    return errors


def read_dataset(folder: str | Path) -> Dataset:
    folder = Path(folder)
    errors: list[str] = []
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise DatasetError([f"{folder}: manifest.json not found"])

    manifest = None
    raw_manifest = _load_json(manifest_path, errors)
    if raw_manifest is not None:
        try:
            manifest = DatasetManifest.model_validate(raw_manifest)
        except ValidationError as exc:
            errors += [f"manifest.json {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]

    parts: dict[str, list] = {}
    for name, (model, required) in FILES.items():
        path = folder / f"{name}.json"
        if not path.is_file():
            if required:
                errors.append(f"{name}.json is required")
            parts[name] = []
            continue
        raw = _load_json(path, errors)
        parts[name] = _validate_list(f"{name}.json", raw, model, errors) if raw is not None else []

    if errors:
        raise DatasetError(errors)
    dataset = Dataset(manifest=manifest, **parts)
    if reference_errors := check_references(dataset):
        raise DatasetError(reference_errors)
    return dataset
