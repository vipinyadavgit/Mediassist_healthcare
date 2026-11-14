"""Independently validate final answer safety and source-reference integrity."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from mediassist_healthcare.agent_models import (
    AgentWorkflowResult,
    SourceEvidence,
    TaskOutcome,
)
from mediassist_healthcare.guardrails import (
    MAX_RESPONSE_CHARACTERS,
    contains_unsafe_treatment_advice,
    mask_sensitive_identifiers,
)

_BRACKETED_REFERENCE = re.compile(r"\[([^\]]+)\]")
_VALID_REFERENCE = re.compile(r"^(?:D|I|M)\d+$")
_SAFE_REFUSAL = (
    "I cannot provide this response because it did not pass the response safety "
    "checks. Please review the source information with a qualified healthcare "
    "professional."
)
_REFUSAL_TASK_REASON = (
    "The response was withheld by the output safety check; ask a qualified "
    "professional to review the request."
)


@dataclass(frozen=True)
class OutputGuardrailDecision:
    """Contain the released result and whether the candidate was withheld."""

    result: AgentWorkflowResult
    blocked: bool
    reason_code: str | None = None


class OutputGuardrail:
    """Fail closed on unsafe answer text or citations outside supplied evidence."""

    def inspect(
        self,
        result: AgentWorkflowResult,
        evidence: list[SourceEvidence],
    ) -> OutputGuardrailDecision:
        """Validate one reasoning result without requesting another model pass."""
        answer = result.answer.strip()
        if not answer or len(answer) > MAX_RESPONSE_CHARACTERS:
            return self._withhold(result, "invalid_answer_length")
        if contains_unsafe_treatment_advice(answer):
            return self._withhold(result, "unsafe_treatment_advice")

        bracketed_references = _BRACKETED_REFERENCE.findall(answer)
        if any(not _VALID_REFERENCE.fullmatch(item) for item in bracketed_references):
            return self._withhold(result, "invalid_citation_format")
        answer_references = set(bracketed_references)
        declared_references = {item.reference for item in result.citations}
        evidence_by_reference: dict[str, SourceEvidence] = {}
        for item in evidence:
            existing = evidence_by_reference.get(item.reference)
            if existing is not None and (
                existing.source != item.source
                or existing.source_type != item.source_type
                or existing.chunk_number != item.chunk_number
            ):
                return self._withhold(result, "conflicting_evidence_reference")
            evidence_by_reference.setdefault(item.reference, item)
        citations_by_reference = {
            item.reference: item for item in result.citations
        }
        if len(citations_by_reference) != len(result.citations):
            return self._withhold(result, "duplicate_answer_citation")
        if (
            answer_references != declared_references
            or not answer_references.issubset(evidence_by_reference)
        ):
            return self._withhold(result, "citation_not_in_evidence")
        if any(
            citation.source != evidence_by_reference[reference].source
            or citation.source_type != evidence_by_reference[reference].source_type
            or citation.chunk_number != evidence_by_reference[reference].chunk_number
            for reference, citation in citations_by_reference.items()
        ):
            return self._withhold(result, "citation_metadata_mismatch")
        if result.status == "answered" and (
            not answer_references
            or not result.task_outcomes
            or any(item.status != "completed" for item in result.task_outcomes)
        ):
            return self._withhold(result, "inconsistent_completion_status")

        return OutputGuardrailDecision(
            result=replace(result, answer=mask_sensitive_identifiers(answer)),
            blocked=False,
        )

    @staticmethod
    def _withhold(
        result: AgentWorkflowResult,
        reason_code: str,
    ) -> OutputGuardrailDecision:
        """Replace a rejected candidate with a fixed refusal and incomplete tasks."""
        outcomes = tuple(
            TaskOutcome(
                task_id=task.task_id,
                description=task.description,
                source=task.source,
                status="incomplete",
                reason=_REFUSAL_TASK_REASON,
            )
            for task in result.task_outcomes
        )
        return OutputGuardrailDecision(
            result=replace(
                result,
                answer=_SAFE_REFUSAL,
                status="insufficient_evidence",
                citations=(),
                task_outcomes=outcomes,
            ),
            blocked=True,
            reason_code=reason_code,
        )
