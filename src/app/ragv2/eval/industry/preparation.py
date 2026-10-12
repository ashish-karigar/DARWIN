"""Processes official RAGChecker raw downloads into its exchange format.

Overview:
    The official repository ships metadata and processing scripts, but those
    scripts assume a particular working directory and an older NovelQA file
    layout. These path-explicit equivalents are resumable and keep every
    generated artifact under DARWIN's ignored external-data directory.
"""

import argparse
import io
import json
from collections.abc import Iterator
from pathlib import Path
from shutil import copyfile

from app.ragv2.eval.industry.config import settings


NOVELQA_BOOKS = (
    "Wuthering Heights",
    "The Old Wives' Tale",
    "The Waves",
    "Ayala's Angel",
    "Winesburg, Ohio",
    "The History of Tom Jones",
    "Can You Forgive Her",
    "Crime And Punishment",
    "Les Miserables",
    "White Fang",
    "Mansfield Park",
    "Marcella",
    "Pride and Prejudice",
    "Dubliners",
    "Lover or Friend",
    "Emma",
    "The History of Rome",
    "Sons and Lovers",
    "Oliver Twist",
)

LOTTE_DOMAINS = (
    "lifestyle",
    "science",
    "writing",
    "recreation",
    "technology",
)


def prepare_novelqa(
    raw_root: Path = settings.raw_root,
    processed_root: Path = settings.processed_root,
    official_processed_root: Path = settings.official_processed_root,
) -> tuple[int, int]:
    source = raw_root / "NovelQA" / "Books" / "PublicDomain"
    destination = processed_root / "novelqa"
    destination.mkdir(parents=True, exist_ok=True)

    missing = [
        title
        for title in NOVELQA_BOOKS
        if not (source / f"{title}.txt").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "NovelQA is missing required books: " + ", ".join(missing)
        )

    corpus_path = destination / "corpus.jsonl"
    with corpus_path.open("w", encoding="utf-8") as handle:
        for index, title in enumerate(NOVELQA_BOOKS, start=1):
            text = (source / f"{title}.txt").read_text(
                encoding="utf-8",
            )
            handle.write(
                json.dumps(
                    {
                        "doc_id": str(index),
                        "title": title,
                        "text": text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    query_source = (
        official_processed_root
        / "novelqa"
        / "novelqa_queries.json"
    )
    if not query_source.is_file():
        raise FileNotFoundError(
            f"Official NovelQA queries not found at {query_source}."
        )
    query_destination = destination / "novelqa_queries.json"
    copyfile(query_source, query_destination)
    query_count = len(
        json.loads(query_destination.read_text())["input_data"]
    )
    return len(NOVELQA_BOOKS), query_count


def prepare_bioasq(
    raw_root: Path = settings.raw_root,
    processed_root: Path = settings.processed_root,
    metadata_root: Path = settings.metadata_root,
) -> tuple[int, int]:
    try:
        import ijson
    except ImportError as exc:
        raise RuntimeError(
            "BioASQ preparation requires ijson in the benchmark "
            "environment."
        ) from exc

    raw = raw_root / "bioasq"
    destination = processed_root / "bioasq"
    destination.mkdir(parents=True, exist_ok=True)

    query_metadata = json.loads(
        (metadata_root / "bioasq_queries_metadata.json").read_text()
    )
    queries = []

    for filename, selected in query_metadata.items():
        query_file = raw / filename
        if not query_file.is_file():
            raise FileNotFoundError(
                f"BioASQ query file not found: {query_file}"
            )
        available = {
            query["id"]: query
            for query in json.loads(
                query_file.read_text(encoding="utf-8")
            )["questions"]
        }
        for metadata in selected:
            query = available[metadata["id"]]
            answer = query["ideal_answer"]
            answer_index = metadata["ideal_answer_index"]
            if answer_index is not None:
                answer = answer[answer_index]
            queries.append(
                {
                    "query_id": query["id"],
                    "query": query["body"],
                    "gt_answer": answer,
                }
            )

    (destination / "bioasq_queries.json").write_text(
        json.dumps({"input_data": queries}, indent=2),
        encoding="utf-8",
    )

    selected_indices = set(
        json.loads(
            (metadata_root / "bioasq_doc_indices.json").read_text()
        )
    )
    corpus_path = destination / "corpus.jsonl"
    document_count = 0

    with (raw / "allMeSH_2022.json").open(
        "rb"
    ) as binary_source, corpus_path.open(
        "w",
        encoding="utf-8",
    ) as output:
        # The official BioASQ dump contains a small number of legacy bytes
        # (for example a Latin-1 degree symbol) inside otherwise UTF-8 JSON.
        # Decode incrementally so the 27 GB file remains streamable, replacing
        # only malformed byte sequences instead of loading or rewriting it.
        source = io.TextIOWrapper(
            binary_source,
            encoding="utf-8",
            errors="replace",
        )
        articles = ijson.items(source, "articles.item")
        for index, article in enumerate(articles):
            if index not in selected_indices:
                continue
            output.write(
                json.dumps(
                    {
                        "doc_id": str(article["pmid"]),
                        "title": article.get("title") or "Untitled",
                        "text": article.get("abstractText") or "",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            document_count += 1

    return document_count, len(queries)


def prepare_lotte(
    raw_root: Path = settings.raw_root,
    processed_root: Path = settings.processed_root,
    metadata_root: Path = settings.metadata_root,
) -> dict[str, tuple[int, int]]:
    lotte_root = raw_root / "lotte"
    results = {}

    for domain in LOTTE_DOMAINS:
        destination = processed_root / domain
        destination.mkdir(parents=True, exist_ok=True)

        forum = _read_lotte_questions(
            _lotte_question_path(raw_root, domain, "forum")
        )
        search = _read_lotte_questions(
            _lotte_question_path(raw_root, domain, "search")
        )
        references = json.loads(
            (metadata_root / f"{domain}_qid2gt.json").read_text()
        )
        queries = []
        for query_id, answer in references.items():
            _, source, _, raw_id = query_id.split("-")
            source_queries = forum if source == "forum" else search
            queries.append(
                {
                    "query_id": query_id,
                    "query": source_queries[raw_id],
                    "gt_answer": answer,
                }
            )
        (destination / f"{domain}_queries.json").write_text(
            json.dumps({"input_data": queries}, indent=2),
            encoding="utf-8",
        )

        indices = json.loads(
            (metadata_root / f"{domain}_doc_indices.json").read_text()
        )
        requested_indices = set(indices)
        raw_documents = {}
        global_index = 0
        for split in ("dev", "test"):
            for text in _iter_lotte_collection(
                lotte_root,
                domain,
                split,
            ):
                if global_index in requested_indices:
                    raw_documents[global_index] = text
                global_index += 1
        missing_indices = requested_indices - raw_documents.keys()
        if missing_indices:
            raise ValueError(
                f"LoTTE {domain} is missing {len(missing_indices)} "
                "selected documents."
            )
        with (destination / "corpus.jsonl").open(
            "w",
            encoding="utf-8",
        ) as handle:
            for index in indices:
                handle.write(
                    json.dumps(
                        {
                            "doc_id": str(index),
                            "text": raw_documents[index],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        results[domain] = (len(indices), len(queries))

    return results


def prepare_clapnq(
    raw_root: Path = settings.raw_root,
    processed_root: Path = settings.processed_root,
    metadata_root: Path = settings.metadata_root,
) -> tuple[int, int]:
    """Builds the official CLAPNQ subset used by RAGChecker."""

    from datasets import load_dataset

    selected_ids = set(
        json.loads((metadata_root / "clapnq_ids.json").read_text())
    )
    validation = load_dataset("PrimeQA/clapnq", split="validation")
    queries = []
    for example in validation:
        if example["id"] not in selected_ids:
            continue
        queries.append(
            {
                "query_id": example["id"],
                "query": example["input"],
                "gt_answer": example["output"][0]["answer"],
            }
        )

    source = raw_root / "clapnq" / "original_documents"
    paths = (
        source / "dev" / "clapnq_dev_answerable_orig.jsonl",
        source / "dev" / "clapnq_dev_unanswerable_orig.jsonl",
        source / "train" / "clapnq_train_answerable_orig.jsonl",
        source / "train" / "clapnq_train_unanswerable_orig.jsonl",
    )
    destination = processed_root / "clapnq"
    destination.mkdir(parents=True, exist_ok=True)
    seen = set()
    document_count = 0
    with (destination / "corpus.jsonl").open("w", encoding="utf-8") as output:
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"CLAPNQ document file not found: {path}")
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    document = json.loads(line)
                    document_id = str(document["example_id"])
                    if document_id in seen:
                        continue
                    seen.add(document_id)
                    output.write(
                        json.dumps(
                            {
                                "doc_id": document_id,
                                "title": document["document_title"],
                                "text": document["document_plaintext"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    document_count += 1
    (destination / "clapnq_queries.json").write_text(
        json.dumps({"input_data": queries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return document_count, len(queries)


def prepare_kiwi(
    processed_root: Path = settings.processed_root,
    metadata_root: Path = settings.metadata_root,
    official_processed_root: Path = settings.official_processed_root,
) -> tuple[int, int]:
    """Combines RAGChecker's KIWI corpus with its selected HF questions."""

    from datasets import load_dataset

    question_ids = json.loads(
        (metadata_root / "kiwi_question_ids.json").read_text()
    )
    data = load_dataset("fangyuan/kiwi", split="train")
    queries = []
    for index, source_index in enumerate(question_ids):
        example = data[source_index]
        queries.append(
            {
                "query_id": str(index),
                "query": example["original_question"],
                "gt_answer": example["interaction"][-1]["answer_1"],
            }
        )
    destination = processed_root / "kiwi"
    destination.mkdir(parents=True, exist_ok=True)
    copyfile(
        official_processed_root / "kiwi" / "corpus.jsonl",
        destination / "corpus.jsonl",
    )
    (destination / "kiwi_queries.json").write_text(
        json.dumps({"input_data": queries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    document_count = sum(
        1 for line in (destination / "corpus.jsonl").open() if line.strip()
    )
    return document_count, len(queries)


def prepare_fiqa(
    processed_root: Path = settings.processed_root,
    metadata_root: Path = settings.metadata_root,
) -> tuple[int, int]:
    """Reuses the official BEIR FiQA download for RAGChecker."""

    beir_directory = processed_root / "beir_fiqa"
    raw_queries = (
        settings.external_root.parent
        / "beir"
        / "raw"
        / "fiqa"
        / "queries.jsonl"
    )
    if not (beir_directory / "corpus.jsonl").is_file():
        raise FileNotFoundError("Prepare the BEIR FiQA dataset first.")
    metadata = json.loads((metadata_root / "fiqa_metadata.json").read_text())
    queries = []
    with raw_queries.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            query_id = str(record["_id"])
            if query_id not in metadata:
                continue
            queries.append(
                {
                    "query_id": query_id,
                    "query": record["text"],
                    "gt_answer": metadata[query_id]["gt_answer"],
                }
            )
    destination = processed_root / "fiqa"
    destination.mkdir(parents=True, exist_ok=True)
    copyfile(beir_directory / "corpus.jsonl", destination / "corpus.jsonl")
    (destination / "fiqa_queries.json").write_text(
        json.dumps({"input_data": queries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    document_count = sum(
        1 for line in (destination / "corpus.jsonl").open() if line.strip()
    )
    return document_count, len(queries)


def _read_lotte_questions(path: Path) -> dict[str, str]:
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            return {
                str(record["qid"]): str(record["query"]).strip()
                for record in (
                    json.loads(line) for line in handle if line.strip()
                )
            }
    with path.open(encoding="utf-8") as handle:
        return {
            query_id: query.strip()
            for query_id, query in (
                line.rstrip("\n").split("\t", 1) for line in handle
            )
        }


def _lotte_question_path(
    raw_root: Path,
    domain: str,
    source: str,
) -> Path:
    candidates = (
        raw_root / "lotte" / domain / "test" / f"questions.{source}.tsv",
        raw_root / "lotte_queries" / domain / f"{source}_test" / "questions.tsv",
        raw_root / "lotte_queries" / domain / "test" / f"questions.{source}.tsv",
        raw_root / "lotte_queries" / domain / f"test_qas.{source}.jsonl",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"LoTTE {domain} {source} questions were not downloaded."
    )


def _iter_lotte_collection(
    lotte_root: Path,
    domain: str,
    split: str,
) -> Iterator[str]:
    tsv_path = lotte_root / domain / split / "collection.tsv"
    if tsv_path.is_file():
        with tsv_path.open(encoding="utf-8") as handle:
            for line in handle:
                yield line.rstrip("\n").split("\t", 1)[1].strip()
        return

    json_path = lotte_root / domain / f"{split}_collection.jsonl"
    if not json_path.is_file():
        raise FileNotFoundError(
            f"LoTTE collection not found for {domain}/{split}."
        )
    with json_path.open("rb") as handle:
        first_byte = handle.read(1)
        handle.seek(0)
        if first_byte == b"[":
            try:
                import ijson
            except ImportError as exc:
                raise RuntimeError(
                    "JSON-array LoTTE collections require ijson."
                ) from exc
            for record in ijson.items(handle, "item"):
                yield str(record["text"]).strip()
        else:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    yield str(record["text"]).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare official RAGChecker benchmark datasets.",
    )
    parser.add_argument(
        "dataset",
        choices=(
            "novelqa",
            "bioasq",
            "lotte",
            "clapnq",
            "kiwi",
            "fiqa",
            "all",
        ),
    )
    arguments = parser.parse_args()

    if arguments.dataset in {"novelqa", "all"}:
        documents, queries = prepare_novelqa()
        print(f"NovelQA: {documents} documents, {queries} queries")
    if arguments.dataset in {"bioasq", "all"}:
        documents, queries = prepare_bioasq()
        print(f"BioASQ: {documents} documents, {queries} queries")
    if arguments.dataset in {"lotte", "all"}:
        for domain, counts in prepare_lotte().items():
            print(
                f"LoTTE {domain}: {counts[0]} documents, "
                f"{counts[1]} queries"
            )
    if arguments.dataset in {"clapnq", "all"}:
        documents, queries = prepare_clapnq()
        print(f"CLAPNQ: {documents} documents, {queries} queries")
    if arguments.dataset in {"kiwi", "all"}:
        documents, queries = prepare_kiwi()
        print(f"KIWI: {documents} documents, {queries} queries")
    if arguments.dataset in {"fiqa", "all"}:
        documents, queries = prepare_fiqa()
        print(f"FiQA: {documents} documents, {queries} queries")


if __name__ == "__main__":
    main()
