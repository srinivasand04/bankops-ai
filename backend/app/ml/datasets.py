"""Time-based train/test splits.

A random split would let a model learn from the future (e.g. train on December, test on June) and
report scores it could never reach in production. Here the oldest 75% is training data and the
newest 25% is the test set - exactly how the model will be used: trained on the past, applied to new
incidents.
"""

from dataclasses import dataclass

import pandas as pd

TEST_FRACTION = 0.25
MIN_ROWS = 60  # below this a task is skipped (e.g. the small demo dataset)


@dataclass
class Split:
    train: pd.DataFrame
    test: pd.DataFrame
    time_col: str

    @property
    def periods(self) -> dict:
        tr, te = self.train[self.time_col], self.test[self.time_col]
        return {"train_from": tr.min(), "train_to": tr.max(), "test_from": te.min(), "test_to": te.max()}


class NotEnoughData(Exception):
    pass


def time_split(df: pd.DataFrame, time_col: str, test_fraction: float = TEST_FRACTION) -> Split:
    if len(df) < MIN_ROWS:
        raise NotEnoughData(f"only {len(df)} rows (need {MIN_ROWS}) - load the large synthetic dataset")
    df = df.sort_values(time_col).reset_index(drop=True)
    cut = int(len(df) * (1 - test_fraction))
    return Split(df.iloc[:cut].copy(), df.iloc[cut:].copy(), time_col)
