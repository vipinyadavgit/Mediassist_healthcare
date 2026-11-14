"""Apply request, privacy, prompt-safety, and response guardrails."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

MAX_QUESTION_CHARACTERS = 4000
MAX_HISTORY_EXCHANGES = 5
MAX_HISTORY_FIELD_CHARACTERS = 1200
MAX_IMAGES_PER_QUESTION = 5
MAX_RESPONSE_CHARACTERS = 6000

_SENSITIVE_PATTERNS = (
    (
        re.compile(
            r"\b(?:MRN|medical record(?: number)?|patient ID|account number)"
            r"\s*[:#]?\s*[A-Z0-9-]{4,}\b",
            re.IGNORECASE,
        ),
        "[REDACTED RECORD IDENTIFIER]",
    ),
    (
        re.compile(
            r"\b(?:SSN|social security number)\s*[:#]?\s*"
            r"\d{3}[- ]?\d{2}[- ]?\d{4}\b",
            re.IGNORECASE,
        ),
        "[REDACTED GOVERNMENT IDENTIFIER]",
    ),
    (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "[REDACTED EMAIL]",
    ),
    (
        re.compile(
            r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?"
            r"\d{3}[-.\s]?\d{4}(?!\w)"
        ),
        "[REDACTED PHONE]",
    ),
    (
        re.compile(
            r"\b(?:DOB|date of birth)\s*[:#]?\s*"
            r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
            r"\d{4}-\d{2}-\d{2})\b",
            re.IGNORECASE,
        ),
        "[REDACTED DATE OF BIRTH]",
    ),
    (
        re.compile(
            r"\b(?:patient name|name)\s*:\s*"
            r"[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,2}\b",
            re.IGNORECASE,
        ),
        "[REDACTED NAME]",
    ),
)
_INSTRUCTION_OVERRIDE_PATTERNS = (
    re.compile(r"\bignore (?:all )?(?:previous|prior) instructions\b", re.IGNORECASE),
    re.compile(r"\breveal (?:the )?(?:system|developer) prompt\b", re.IGNORECASE),
    re.compile(r"\bshow (?:me )?(?:the )?(?:system|developer) prompt\b", re.IGNORECASE),
    re.compile(r"\bdisregard (?:all )?(?:previous|prior) rules\b", re.IGNORECASE),
)
_UNSAFE_TREATMENT_PATTERNS = (
    re.compile(
        r"\b(?:you should|i recommend|i advise|you must)\b"
        r".{0,80}\b(?:take|stop|start|increase|decrease|adjust|change|"
        r"discontinue)\b.{0,50}\b(?:medicine|medication|drug|dose|dosage|"
        r"prescription|treatment)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:take|stop|start|increase|decrease|adjust|change|discontinue)"
        r"\s+(?:your\s+|the\s+)?(?:medicine|medication|drug|dose|dosage|"
        r"prescription|treatment)\b",
        re.IGNORECASE,
    ),
)


class GuardrailViolation(ValueError):
    """Report input or output rejected by a configured safety guardrail."""


@dataclass(frozen=True)
class ConversationTurn:
    """Keep one bounded prior user/assistant exchange for planning context."""

    question: str
    answer: str


def validate_question(question: str) -> str:
    """Normalize a user question and enforce the bounded input contract."""
    normalized = question.strip()
    if not normalized:
        raise GuardrailViolation("Enter a question before submitting.")
    if len(normalized) > MAX_QUESTION_CHARACTERS:
        raise GuardrailViolation(
            f"Questions must be {MAX_QUESTION_CHARACTERS} characters or fewer."
        )
    if any(ord(character) < 32 and character not in "\n\t\r" for character in normalized):
        raise GuardrailViolation("The question contains unsupported control characters.")
    return normalized


def validate_history(history: Iterable[ConversationTurn]) -> list[ConversationTurn]:
    """Keep only the five most recent bounded conversation exchanges."""
    bounded: list[ConversationTurn] = []
    for turn in list(history)[-MAX_HISTORY_EXCHANGES:]:
        question = turn.question.strip()[:MAX_HISTORY_FIELD_CHARACTERS]
        answer = turn.answer.strip()[:MAX_HISTORY_FIELD_CHARACTERS]
        if question and answer:
            bounded.append(ConversationTurn(question=question, answer=answer))
    return bounded


def mask_sensitive_identifiers(text: str) -> str:
    """Best-effort mask common direct identifiers before model calls or display."""
    masked = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked


def contains_instruction_override(text: str) -> bool:
    """Detect common attempts to replace system instructions or reveal prompts."""
    return any(pattern.search(text) for pattern in _INSTRUCTION_OVERRIDE_PATTERNS)


def contains_unsafe_treatment_advice(text: str) -> bool:
    """Detect the limited set of direct treatment instructions blocked by policy."""
    return any(pattern.search(text) for pattern in _UNSAFE_TREATMENT_PATTERNS)


def enforce_safe_output(answer: str) -> str:
    """Bound and sanitize model output, replacing direct treatment advice."""
    normalized = mask_sensitive_identifiers(answer.strip())
    if not normalized:
        raise GuardrailViolation("The response did not contain usable text.")
    if len(normalized) > MAX_RESPONSE_CHARACTERS:
        normalized = normalized[:MAX_RESPONSE_CHARACTERS].rsplit(" ", maxsplit=1)[0]
    if contains_unsafe_treatment_advice(normalized):
        return (
            "I can summarize information in the provided sources, but I cannot "
            "recommend starting, stopping, or changing treatment. Please consult "
            "a qualified healthcare professional for individual medical advice."
        )
    return normalized
