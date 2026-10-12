"""Paths and dataset choices for isolated industry benchmarks."""

from dataclasses import dataclass
from pathlib import Path

from app.ragv2.config import PROJECT_ROOT


@dataclass(frozen=True, slots=True)
class IndustryBenchmarkSettings:
    external_root: Path = (
        PROJECT_ROOT / "data" / "external" / "ragchecker"
    )
    output_root: Path = (
        PROJECT_ROOT / "data" / "ragv2" / "industry_benchmarks"
    )
    daily_groq_token_limit: int = 200_000
    daily_token_reserve: int = 10_000
    calibration_sample_size: int = 50

    @property
    def raw_root(self) -> Path:
        return self.external_root / "raw_data"

    @property
    def processed_root(self) -> Path:
        return self.external_root / "processed_data"

    @property
    def vendor_root(self) -> Path:
        return self.external_root / "vendor" / "RAGChecker"

    @property
    def metadata_root(self) -> Path:
        return self.vendor_root / "data" / "benchmark" / "metadata"

    @property
    def official_processed_root(self) -> Path:
        return (
            self.vendor_root
            / "data"
            / "benchmark"
            / "processed_data"
        )

    @property
    def index_root(self) -> Path:
        return self.output_root / "indexes"

    @property
    def run_root(self) -> Path:
        return self.output_root / "runs"

    @property
    def report_root(self) -> Path:
        return self.output_root / "reports"


settings = IndustryBenchmarkSettings()


REPRESENTATIVE_BEIR_DATASETS = (
    "scifact",
    "nfcorpus",
    "fiqa",
    "arguana",
)
