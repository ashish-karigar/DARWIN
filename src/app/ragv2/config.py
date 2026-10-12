import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def environment_flag(
    name: str,
    default: bool = False,
) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True, slots=True)
class RagSettings:
    data_directory: Path = PROJECT_ROOT / "data" / "ragv2"
    parsed_directory: Path = data_directory / "parsed"

    document_store_path: Path = (
        data_directory / "indexes" / "documents.sqlite3"
    )
    vector_index_directory: Path = (
        data_directory / "indexes" / "chroma"
    )
    lexical_index_path: Path = (
        data_directory / "indexes" / "lexical.sqlite3"
    )
    structured_index_path: Path = (
        data_directory / "indexes" / "structured.sqlite3"
    )

    vector_collection_name: str = "darwin_ragv2_chunks"
    embedding_model: str = "nomic-embed-text"
    embedding_batch_size: int = 32

    retrieval_candidate_limit: int = 20
    retrieval_result_limit: int = 5
    retrieval_parallel_workers: int = 4
    rrf_rank_constant: int = 60
    vector_retriever_weight: float = 1.0
    lexical_retriever_weight: float = 1.0

    reranker_model: str = (
        "cross-encoder/ms-marco-MiniLM-L6-v2"
    )
    reranker_batch_size: int = 16
    reranker_result_limit: int = 5
    evidence_relevance_threshold: float = 0.65
    evidence_fast_path_threshold: float = 0.85
    evidence_reject_threshold: float = 0.10
    evidence_fast_path_limit: int = 3
    evidence_corroborated_limit: int = 5
    evidence_hybrid_corroboration_threshold: float = 0.85
    evidence_vector_corroboration_threshold: float = 0.60
    evidence_lexical_corroboration_threshold: float = 0.42
    evidence_query_anchor_coverage_threshold: float = 0.75
    minimum_direct_evidence: int = 1

    context_max_tokens: int = 3000
    context_max_parents: int = 5
    context_parents_per_requirement: int = 1
    context_preferred_parents_per_document: int = 2
    context_fragment_max_tokens: int = 80
    context_fragment_window: int = 4
    context_fragment_group_max_tokens: int = 256

    generation_max_attempts: int = 2
    verification_regeneration_limit: int = 1
    verification_support_threshold: float = 0.70
    verification_lexical_fast_path_threshold: float = 0.75
    verification_semantic_fast_path_threshold: float = 0.85
    corrective_retrieval_limit: int = 1
    web_search_result_limit: int = 5
    structured_evidence_row_limit: int = 20

    query_analysis_history_messages: int = 6

    default_encoding: str = "utf-8"
    maximum_file_size_mb: int = 50
    request_timeout_seconds: float = 30.0
    maximum_web_redirects: int = 5
    maximum_query_characters: int = 4000
    maximum_conversation_characters: int = 12000
    maximum_conversation_messages: int = 20
    child_chunk_tokens: int = 384
    child_chunk_overlap_tokens: int = 64
    table_chunk_tokens: int = 512
    table_chunk_overlap_rows: int = 1

    enable_assisted_parsing: bool = field(
        default_factory=lambda: environment_flag(
            "DARWIN_ENABLE_ASSISTED_PARSING",
        )
    )
    enable_llm_evidence_grading: bool = field(
        default_factory=lambda: environment_flag(
            "DARWIN_ENABLE_LLM_EVIDENCE_GRADING",
            default=False,
        )
    )


settings = RagSettings()
