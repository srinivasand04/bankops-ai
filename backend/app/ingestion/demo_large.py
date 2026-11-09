"""Hosted demo: load 12 months of synthetic history in the background after the server starts.

The free hosted database resets on every start and would otherwise hold only the 15-incident demo set,
which makes reports, trends and ML insights look empty. The generator is seeded, so every start builds
the same history (dated up to today): 4,000 incidents, 648 changes, and the last 14 days of hourly
metrics (older metrics are left out to keep the free database small and the load quick).

It runs in a background thread so the API answers health checks and visitors straight away; the
history appears within a minute or two.
"""

import logging
import tempfile
import threading
import time
from pathlib import Path

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.ingestion.loader import load_dataset
from app.ingestion.reader import read_dataset
from app.models import Application
from app.synthetic.generator import DATA_SOURCE, GeneratorConfig, SyntheticGenerator, write_dataset

logger = logging.getLogger(__name__)

STATE: dict = {"state": "IDLE"}


def already_loaded() -> bool:
    with SessionLocal() as db:
        return bool(db.scalar(select(func.count()).select_from(Application).where(Application.data_source == DATA_SOURCE)))


def load_large_demo(months: int = 12, scale: float = 1.0, evidence_days: int = 14) -> dict:
    """Generate and load the seeded history unless it is already there. Returns the load counts."""
    if already_loaded():
        STATE.update(state="DONE", note="already loaded")
        return STATE
    STATE.update(state="RUNNING", started=time.time())
    try:
        generator = SyntheticGenerator(GeneratorConfig(seed=42, months=months, scale=scale, evidence_days=evidence_days))
        with tempfile.TemporaryDirectory() as tmp:
            write_dataset(generator.generate(), Path(tmp))
            dataset = read_dataset(tmp)
        with SessionLocal() as db:
            report = load_dataset(db, dataset)
        STATE.update(state="DONE", counts=report.counts, seconds=round(time.time() - STATE["started"], 1))
        logger.info("Loaded the large demo history in %.0f s: %s", STATE["seconds"], report.counts)
    except Exception as exc:  # the demo must keep running even if this fails
        STATE.update(state="FAILED", error=f"{type(exc).__name__}: {exc}"[:300])
        logger.exception("Could not load the large demo history")
    return STATE


def start_in_background() -> threading.Thread:
    thread = threading.Thread(target=load_large_demo, name="large-demo-load", daemon=True)
    thread.start()
    return thread
