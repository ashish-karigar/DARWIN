"""Append-only checkpoint storage for multi-day benchmark runs."""

from pathlib import Path

from app.ragv2.eval.industry.contracts import BenchmarkSample


class BenchmarkCheckpoint:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> tuple[BenchmarkSample, ...]:
        if not self.path.is_file():
            return ()

        samples = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    samples.append(
                        BenchmarkSample.model_validate_json(line)
                    )
                except Exception as exc:
                    raise ValueError(
                        f"Invalid checkpoint record at "
                        f"{self.path}:{line_number}."
                    ) from exc
        return tuple(samples)

    def completed_ids(self) -> set[str]:
        return {sample.query_id for sample in self.load()}

    def append(self, sample: BenchmarkSample) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(sample.model_dump_json() + "\n")
            handle.flush()
