"""One module per ML task. Each exposes `train(db) -> TaskOutput`."""

from dataclasses import dataclass, field

from app.ml.registry import RunResult


@dataclass
class TaskOutput:
    results: list[RunResult]
    periods: dict
    n_train: int
    n_test: int
    shared: dict = field(default_factory=dict)  # saved with every artifact (e.g. feature columns)
