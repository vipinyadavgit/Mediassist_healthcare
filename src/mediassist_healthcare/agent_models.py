"""Share typed request, plan, evidence, and outcome records across agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mediassist_healthcare.retriever import RetrievalMode

AgentSource = Literal["documents", "images", "mcp"]
AgentStatus = Literal["completed", "incomplete"]
WorkflowStatus = Literal[
    "answered",
    "partial",
    "out_of_scope",
    "insufficient_evidence",
]
TraceStatus = Literal["completed", "failed"]


@dataclass(frozen=True)
class WorkflowTraceEntry:
    """Expose one content-free LangGraph node execution to the session UI."""

    node: str
    status: TraceStatus
    duration_ms: int
    detail: str


@dataclass(frozen=True)
class PlannedTask:
    """Describe one bounded step and the evidence source assigned to it."""

    task_id: str
    description: str
    source: AgentSource


@dataclass(frozen=True)
class AgentPlan:
    """Represent the planner's validated intent, complexity, and task list."""

    intent: str
    complexity: Literal["single_step", "multi_step"]
    in_scope: bool
    tasks: tuple[PlannedTask, ...]


@dataclass(frozen=True)
class EvidenceGap:
    """Provide bounded, task-specific feedback for one evidence recovery pass."""

    task_id: str
    source: Literal["documents", "images"]
    description: str
    reason: str


@dataclass(frozen=True)
class SourceEvidence:
    """Associate one evidence item with its source and planned task."""

    reference: str
    task_id: str
    source_type: Literal["documents", "images"]
    source: str
    text: str
    chunk_number: int
    distance: float | None = None


@dataclass(frozen=True)
class TaskOutcome:
    """Explain whether a planned task was completed and why."""

    task_id: str
    description: str
    source: AgentSource
    status: AgentStatus
    reason: str


@dataclass(frozen=True)
class AgentCitation:
    """Expose a safe source reference in the chat API response."""

    reference: str
    source: str
    chunk_number: int
    source_type: Literal["documents", "images"]
    distance: float | None = None


@dataclass(frozen=True)
class AgentWorkflowResult:
    """Return a grounded answer, task outcomes, and source references."""

    answer: str
    status: WorkflowStatus
    citations: tuple[AgentCitation, ...]
    task_outcomes: tuple[TaskOutcome, ...]
    intent: str
    complexity: Literal["single_step", "multi_step"]
    retrieval_mode: RetrievalMode
    model: str
    traces: tuple[WorkflowTraceEntry, ...] = ()
