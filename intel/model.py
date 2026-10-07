"""The bid price model's interface: what the advisor asks, whichever model answers.

A Predictor answers two questions about a tender:
  * ratio_quantiles: the distribution of r = ln(lowest price / estimate) in an auction with
    a given number of bids, as 19 calibrated quantiles;
  * bidders_pmf: how many bids the tender is likely to draw.
Implementations (LightGBM, and the B0 baseline every model must beat) live behind this
interface and are saved under data/intel/models/<version>/ with a meta.json whose "kind"
picks the loader. The active version is the ModelVersion row with is_active=True.
"""

import contextlib
import importlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
from django.conf import settings

log = logging.getLogger(__name__)

QUANTILES: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(1, 20))  # 0.05..0.95
MAX_BIDDERS = 30
MODELS_DIR = Path(settings.BASE_DIR) / "data" / "intel" / "models"


@dataclass(frozen=True)
class Features:
    """What is known about a tender before bids open. Never the number of bids, the award
    date or anything else from the result: that would leak the answer."""

    estimated_inr_real: float  # the estimate in today's rupees, > 0
    country: str = "IN"
    state: str = ""
    sector: str = ""
    category: str = ""  # works | goods | services | consultancy | ""
    method: str = ""  # HistoricalAward.Method value or ""
    year: int = field(default_factory=lambda: date.today().year)
    buyer_key: str = ""


class Predictor:
    """Base class. Subclasses implement the two predictions and load/save."""

    kind: str = "base"

    def __init__(self, version: str = "", card: dict | None = None):
        self.version = version
        self.card = card or {}

    def ratio_quantiles(self, f: Features, num_bidders: int) -> np.ndarray:
        """Shape (len(QUANTILES),), sorted ascending, conformal-adjusted quantiles of
        ln(lowest bid / estimate) for an auction with `num_bidders` bids (>= 1)."""
        raise NotImplementedError

    def bidders_pmf(self, f: Features) -> np.ndarray:
        """Shape (MAX_BIDDERS + 1,): P(total bids = n) for n = 0..MAX_BIDDERS; p[0] = 0 and
        the vector sums to 1 (the tail beyond MAX_BIDDERS is folded into the last cell)."""
        raise NotImplementedError

    def save(self, path: Path) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path, meta: dict) -> "Predictor":
        raise NotImplementedError


# kind -> Predictor subclass; implementations register themselves (intel.train imports
# them, and load_active imports intel.predictors to make sure they are registered).
LOADERS: dict[str, type[Predictor]] = {}


def register_kind(cls: type[Predictor]) -> type[Predictor]:
    LOADERS[cls.kind] = cls
    return cls


def load_path(path: Path) -> Predictor:
    meta = json.loads((path / "meta.json").read_text())
    # Importing the implementations registers them in LOADERS.
    with contextlib.suppress(ImportError):  # only before intel/predictors.py exists
        importlib.import_module("intel.predictors")
    cls = LOADERS[meta["kind"]]
    predictor = cls.load(path, meta)
    predictor.version = meta.get("version", path.name)
    predictor.card = meta.get("card", {})
    return predictor


_lock = threading.Lock()
_cache: dict[str, Predictor] = {}


def load_active() -> Predictor | None:
    """The active model, loaded once per process and reloaded when another version is
    activated. None when no model is active or its files are missing."""
    from intel.models import ModelVersion

    row = ModelVersion.objects.filter(is_active=True).only("version", "path").first()
    if row is None:
        return None
    with _lock:
        cached = _cache.get("active")
        if cached is not None and cached.version == row.version:
            return cached
        path = Path(row.path)
        if not path.is_absolute():
            path = MODELS_DIR / path
        try:
            predictor = load_path(path)
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            log.error("active model %s cannot be loaded from %s: %s", row.version, path, exc)
            return None
        predictor.version = row.version
        _cache["active"] = predictor
        return predictor
