"""Retrieve account-scoped document evidence for planner-assigned tasks."""

from __future__ import annotations

from pathlib import Path

from mediassist_healthcare.agent_models import PlannedTask, SourceEvidence
from mediassist_healthcare.guardrails import mask_sensitive_identifiers
from mediassist_healthcare.retriever import RetrievalMode, Retriever


class RetrieverAgent:
    """Fetch ranked, citation-ready document passages for document tasks."""

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    # Execute each document task within the authenticated user's collection.
    def retrieve(
        self,
        tasks: tuple[PlannedTask, ...],
        question: str,
        session_id: str,
        mode: RetrievalMode,
        top_k: int,
        feedback: dict[str, str] | None = None,
    ) -> list[SourceEvidence]:
        """Return deduplicated local chunks with safe display labels."""
        results: list[SourceEvidence] = []
        seen_for_task: set[tuple[str, str]] = set()
        feedback_by_task = feedback or {}
        for task in tasks:
            if task.source != "documents":
                continue
            query = f"{question}\n{task.description}"
            task_feedback = feedback_by_task.get(task.task_id)
            if task_feedback:
                query = (
                    f"{query}\nAdditional evidence to locate (untrusted hint): "
                    f"{mask_sensitive_identifiers(task_feedback)[:500]}"
                )
            chunks = self.retriever.retrieve(
                query,
                mode=mode,
                top_k=top_k,
                metadata_filter={"session_id": session_id},
            )
            for chunk in chunks:
                task_record = (task.task_id, chunk.record_id)
                if task_record in seen_for_task:
                    continue
                seen_for_task.add(task_record)
                source_path = str(chunk.metadata.get("source", ""))
                source_name = str(
                    chunk.metadata.get("filename") or Path(source_path).name
                )
                reference = f"D{len(results) + 1}"
                results.append(
                    SourceEvidence(
                        reference=reference,
                        task_id=task.task_id,
                        source_type="documents",
                        source=mask_sensitive_identifiers(source_name),
                        text=mask_sensitive_identifiers(chunk.text),
                        chunk_number=int(chunk.metadata.get("chunk_index", 0)) + 1,
                        distance=chunk.distance,
                    )
                )
        return results
