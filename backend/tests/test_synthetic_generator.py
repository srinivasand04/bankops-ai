"""Large synthetic dataset generator: determinism, validity through the real ingestion pipeline, and the
designed signal (so the ML tasks in later phases have something real to learn)."""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median

import pytest

from app.ingestion.loader import dry_run, load_dataset
from app.ingestion.reader import read_dataset
from app.synthetic.catalog import APP_BY_CODE, APPS, PROBLEMS
from app.synthetic.generator import (
    DOWN_METRICS,
    GeneratorConfig,
    SyntheticGenerator,
    in_change_window,
    write_dataset,
)

END = datetime(2026, 11, 5, tzinfo=UTC)


def _generate(seed=11, months=2, scale=0.1):
    generator = SyntheticGenerator(GeneratorConfig(seed=seed, months=months, scale=scale, end=END))
    return generator, generator.generate()


@pytest.fixture(scope="module")
def year():
    """A full year at half scale: big enough for stable signal checks, fast (no database)."""
    return _generate(seed=42, months=12, scale=0.5)


# ---- determinism ---------------------------------------------------------------------------------


def test_same_seed_gives_identical_output():
    _, first = _generate(seed=11)
    _, second = _generate(seed=11)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_different_seed_gives_different_output():
    _, first = _generate(seed=11)
    _, other = _generate(seed=12)
    assert first["incidents"] != other["incidents"]


def test_written_files_are_identical(tmp_path):
    _, data = _generate(seed=5)
    a, b = tmp_path / "a", tmp_path / "b"
    write_dataset(data, a)
    write_dataset(_generate(seed=5)[1], b)
    for file in a.iterdir():
        assert file.read_bytes() == (b / file.name).read_bytes()


# ---- validity through the real ingestion pipeline -----------------------------------------------


def test_output_passes_schema_references_and_lifecycle_replay(db, tmp_path):
    _, data = _generate()
    write_dataset(data, tmp_path / "ds")
    dataset = read_dataset(tmp_path / "ds")  # schema + references
    report = dry_run(db, dataset)  # every incident history replayed through the state machine
    assert dataset.manifest.data_source == "SYNTHETIC_LARGE"
    assert report.counts["incidents"] == len(data["incidents"])
    assert report.counts["applications"] == len(APPS)  # standalone: owns all applications


def test_loads_next_to_the_demo_dataset(db, seeded, tmp_path):
    _, data = _generate()
    write_dataset(data, tmp_path / "ds")
    report = load_dataset(db, read_dataset(tmp_path / "ds"))
    assert report.counts["applications"] == len(APPS) - 5  # the 5 demo applications are reused, not taken over
    assert report.counts["incidents"] == len(data["incidents"])
    assert report.counts["operational_events"] == len(data["operational_events"])


# ---- designed signal -------------------------------------------------------------------------------


def test_risky_changes_cause_more_incidents(year):
    generator, _ = year
    risky = [c for c in generator.changes if c.deployed.weekday() == 4 or not in_change_window(c.deployed)]
    safe = [c for c in generator.changes if c not in risky]
    rate = lambda cs: sum(c.caused for c in cs) / len(cs)  # noqa: E731
    assert rate(risky) > 2 * rate(safe)
    large = [c for c in generator.changes if c.record["components_changed"] >= 10]
    small = [c for c in generator.changes if c.record["components_changed"] <= 2]
    assert rate(large) > rate(small)


def test_caused_incidents_start_within_six_hours(year):
    generator, _ = year
    gaps = [(i.start - i.change.deployed) for i in generator.incidents if i.change is not None]
    assert gaps and all(timedelta(minutes=10) <= g <= timedelta(hours=6) for g in gaps)


def test_severity_depends_on_tier(year):
    generator, _ = year
    p1_share = {}
    for tier in ("TIER_1", "TIER_3"):
        incidents = [i for i in generator.incidents if i.app.tier == tier]
        p1_share[tier] = sum(i.severity in ("P1", "P2") for i in incidents) / len(incidents)
    assert p1_share["TIER_1"] > 2 * p1_share["TIER_3"]


def test_mttr_is_longer_relative_to_target_for_p1_and_infrastructure(year):
    from app.core.config import DEFAULT_SLA_TARGETS

    generator, _ = year
    ratios = defaultdict(list)
    for i in generator.incidents:
        if i.resolved:
            ratio = (i.resolved - i.start).total_seconds() / 60 / DEFAULT_SLA_TARGETS[i.severity].resolution
            ratios[i.severity].append(ratio)
            ratios["infra" if i.category in ("INFRASTRUCTURE", "NETWORK") else "other"].append(ratio)
    assert median(ratios["P1"]) > median(ratios["P4"])
    assert median(ratios["infra"]) > median(ratios["other"])


def test_recurring_problems_repeat(year):
    generator, _ = year
    counts = Counter(i.problem.key for i in generator.incidents if i.problem)
    assert set(counts) == {p.key for p in PROBLEMS}
    assert all(n >= 5 for n in counts.values())


def test_metric_anomalies_precede_major_incidents(year):
    generator, data = year
    series = defaultdict(dict)
    for e in data["operational_events"]:
        if e["event_type"] == "METRIC" and e["metric_name"] == APP_BY_CODE[e["application"]].metric[0]:
            series[e["application"]][e["occurred_at"]] = e["metric_value"]
    medians = {app: median(values.values()) for app, values in series.items()}
    hits = total = 0
    for i in generator.incidents:
        if i.severity not in ("P1", "P2") or i.app.metric[0] in DOWN_METRICS:
            continue
        before = i.start.replace(minute=0, second=0)  # the hourly point at or just before the start
        value = series[i.app.code].get(before.isoformat().replace("+00:00", "Z"))
        if value is not None:
            total += 1
            hits += value > 1.8 * medians[i.app.code]
    assert total > 50 and hits / total > 0.8


def test_noise_and_missing_fields_are_present(year):
    generator, data = year
    noisy = sum(i.record["category"] != i.category for i in generator.incidents) / len(generator.incidents)
    assert 0.02 < noisy < 0.09  # about 5% label noise
    missing_impact = sum("business_impact" not in r for r in data["incidents"]) / len(data["incidents"])
    assert 0.08 < missing_impact < 0.25


def test_every_application_has_incidents_and_metrics(year):
    generator, data = year
    assert {i.app.code for i in generator.incidents} == set(APP_BY_CODE)
    assert {e["application"] for e in data["operational_events"] if e["event_type"] == "METRIC"} == set(APP_BY_CODE)


def test_evidence_days_trims_only_metrics_and_job_runs():
    from datetime import timedelta

    full = SyntheticGenerator(GeneratorConfig(seed=11, months=2, scale=0.3)).generate()
    trimmed = SyntheticGenerator(GeneratorConfig(seed=11, months=2, scale=0.3, evidence_days=7)).generate()
    assert trimmed["incidents"] == full["incidents"] and trimmed["changes"] == full["changes"]
    assert len(trimmed["operational_events"]) < len(full["operational_events"]) / 3
    end = SyntheticGenerator(GeneratorConfig(seed=11, months=2, scale=0.3)).cfg.end
    from app.synthetic.generator import iso

    cutoff = iso(end - timedelta(days=7))
    old = [e for e in trimmed["operational_events"] if e["event_type"] in ("METRIC", "JOB_RUN") and e["occurred_at"] < cutoff]
    assert old == []
    assert any(e["event_type"] == "ALERT" and e["occurred_at"] < cutoff for e in trimmed["operational_events"])


def test_large_demo_loads_once(db, monkeypatch):
    from app.ingestion import demo_large

    first = demo_large.load_large_demo(months=2, scale=0.2, evidence_days=3)
    assert first["state"] == "DONE" and first["counts"]["incidents"] > 50
    assert demo_large.load_large_demo(months=2, scale=0.2)["note"] == "already loaded"
