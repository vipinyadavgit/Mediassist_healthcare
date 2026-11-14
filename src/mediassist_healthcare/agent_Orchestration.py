"""Orchestrate the MediAssist specialist agents with LangGraph."""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith.run_helpers import tracing_context

from mediassist_healthcare.agent_models import (
    AgentPlan,
    AgentWorkflowResult,
    EvidenceGap,
    SourceEvidence,
    WorkflowTraceEntry,
)
from mediassist_healthcare.guardrails import (
    ConversationTurn,
    GuardrailViolation,
    MAX_IMAGES_PER_QUESTION,
    mask_sensitive_identifiers,
    validate_history,
    validate_question,
)
from mediassist_healthcare.multimodal_agent import (
    ExternalVisionDisabledError,
    ImageInput,
    ImageObservation,
    MultimodalAgent,
)
from mediassist_healthcare.observability import WorkflowObservation, WorkflowObserver
from mediassist_healthcare.output_guardrail import OutputGuardrail
from mediassist_healthcare.planner_agent import PlannerAgent
from mediassist_healthcare.reasoning_agent import ReasoningAgent
from mediassist_healthcare.retriever import RetrievalMode
from mediassist_healthcare.retriever_agent import RetrieverAgent
from mediassist_healthcare.settings import external_vision_is_enabled

MAX_EVIDENCE_RECOVERY_RETRIES = 1


class AgentWorkflowState(TypedDict, total=False):
    """Data passed between graph nodes; source content stays out of traces."""

    question: str
    session_id: str
    top_k: int
    mode: RetrievalMode
    images: list[ImageInput]
    history: list[ConversationTurn]
    plan: AgentPlan
    evidence: list[SourceEvidence]
    observations: list[ImageObservation]
    result: AgentWorkflowResult
    retry_count: int
    retry_feedback: list[EvidenceGap]
    guardrail_blocked: bool
    traces: list[WorkflowTraceEntry]
    observation: WorkflowObservation


class AgentWorkflow:
    """Run planning, retrieval, optional image analysis, and reasoning as a graph."""

    def __init__(
        self,
        planner: PlannerAgent,
        retriever: RetrieverAgent,
        multimodal: MultimodalAgent,
        reasoner: ReasoningAgent,
        observer: WorkflowObserver | None = None,
        output_guardrail: OutputGuardrail | None = None,
    ) -> None:
        self.planner = planner
        self.retriever = retriever
        self.multimodal = multimodal
        self.reasoner = reasoner
        self.observer = observer or WorkflowObserver()
        self.output_guardrail = output_guardrail or OutputGuardrail()
        graph = StateGraph(AgentWorkflowState)
        graph.add_node("plan", self._plan_node)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("analyze_images", self._analyze_images_node)
        graph.add_node("reason", self._reason_node)
        graph.add_node("output_guardrail", self._output_guardrail_node)
        graph.add_node("prepare_retry", self._prepare_retry_node)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            self._route_after_planning,
            {
                "retrieve": "retrieve",
                "analyze_images": "analyze_images",
                "reason": "reason",
            },
        )
        graph.add_conditional_edges(
            "retrieve",
            self._route_after_retrieval,
            {"analyze_images": "analyze_images", "reason": "reason"},
        )
        graph.add_edge("analyze_images", "reason")
        graph.add_edge("reason", "output_guardrail")
        graph.add_conditional_edges(
            "output_guardrail",
            self._route_after_output_guardrail,
            {"retry": "prepare_retry", "done": END},
        )
        graph.add_conditional_edges(
            "prepare_retry",
            self._route_after_retry_preparation,
            {
                "retrieve": "retrieve",
                "analyze_images": "analyze_images",
                "reason": "reason",
            },
        )
        self._graph = graph.compile()

    # Validate untrusted inputs before invoking any external agent.
    def run(
        self,
        question: str,
        session_id: str,
        top_k: int = 5,
        mode: RetrievalMode = "hybrid",
        images: list[ImageInput] | None = None,
        history: list[ConversationTurn] | None = None,
        external_image_approved: bool = False,
    ) -> AgentWorkflowResult:
        """Return a grounded answer with content-free node timing traces."""
        normalized_question = validate_question(question)
        bounded_history = validate_history(history or [])
        selected_images = images or []
        if len(selected_images) > MAX_IMAGES_PER_QUESTION:
            raise GuardrailViolation(
                f"Use no more than {MAX_IMAGES_PER_QUESTION} images per question."
            )
        if selected_images and not external_image_approved:
            raise GuardrailViolation(
                "Confirm that the selected images are approved for external "
                "processing before asking a question about them."
            )
        if selected_images and not external_vision_is_enabled():
            raise ExternalVisionDisabledError(
                "Image analysis is disabled by the server's privacy settings. "
                "An administrator must approve external image processing first."
            )

        observation = self.observer.start(mode, len(selected_images))
        started = perf_counter()
        try:
            with tracing_context(enabled=False):
                final_state = self._graph.invoke(
                    {
                        "question": normalized_question,
                        "session_id": session_id,
                        "top_k": top_k,
                        "mode": mode,
                        "images": selected_images,
                        "history": bounded_history,
                        "retry_count": 0,
                        "retry_feedback": [],
                        "guardrail_blocked": False,
                        "traces": [],
                        "observation": observation,
                    }
                )
            result = final_state.get("result")
            if result is None:
                raise RuntimeError("The LangGraph workflow completed without a result.")
        except Exception as error:
            observation.finish(
                error=error,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise

        observation.finish(
            result=result,
            duration_ms=round((perf_counter() - started) * 1000),
        )
        return replace(result, traces=tuple(final_state.get("traces", [])))

    def _plan_node(self, state: AgentWorkflowState) -> dict[str, object]:
        started = perf_counter()
        try:
            plan = self.planner.plan(
                state["question"],
                history=state.get("history", []),
                image_sources=[image.name for image in state.get("images", [])],
            )
        except Exception as error:
            self._record_node_failure(state, "Planner", started, error)
            raise
        return {
            "plan": plan,
            "traces": self._append_trace(
                state,
                "Planner",
                started,
                f"Classified request and created {len(plan.tasks)} task(s).",
                {"task_count": len(plan.tasks)},
            ),
        }

    def _retrieve_node(self, state: AgentWorkflowState) -> dict[str, object]:
        started = perf_counter()
        feedback = state.get("retry_feedback", [])
        if feedback:
            feedback_by_task = {
                item.task_id: item.reason for item in feedback
                if item.source == "documents"
            }
            target_task_ids = set(feedback_by_task)
            tasks = tuple(
                task for task in state["plan"].tasks
                if task.task_id in target_task_ids
            )
        else:
            feedback_by_task = {}
            target_task_ids = set()
            tasks = state["plan"].tasks
        try:
            evidence = self.retriever.retrieve(
                tasks,
                state["question"],
                state["session_id"],
                state.get("mode", "hybrid"),
                state.get("top_k", 5),
                feedback=feedback_by_task or None,
            )
        except Exception as error:
            self._record_node_failure(state, "Retriever", started, error)
            raise
        if target_task_ids:
            existing_evidence = [
                item for item in state.get("evidence", [])
                if item.task_id not in target_task_ids
            ]
            next_reference_number = max(
                (
                    int(item.reference[1:])
                    for item in existing_evidence
                    if item.reference.startswith("D")
                    and item.reference[1:].isdigit()
                ),
                default=0,
            ) + 1
            evidence = [
                *existing_evidence,
                *[
                    replace(item, reference=f"D{next_reference_number + index}")
                    for index, item in enumerate(evidence)
                ],
            ]
        return {
            "evidence": evidence,
            "traces": self._append_trace(
                state,
                "Retriever",
                started,
                f"Retrieved {len(evidence)} evidence passage(s).",
                {"evidence_count": len(evidence)},
            ),
        }

    def _analyze_images_node(self, state: AgentWorkflowState) -> dict[str, object]:
        started = perf_counter()
        feedback = [
            mask_sensitive_identifiers(f"{item.description}: {item.reason}")[:1000]
            for item in state.get("retry_feedback", [])
            if item.source == "images"
        ]
        try:
            images = self.multimodal.analyze(
                state["question"],
                state.get("images", []),
                feedback=feedback or None,
            )
        except Exception as error:
            self._record_node_failure(state, "Multimodal", started, error)
            raise
        return {
            "observations": images,
            "traces": self._append_trace(
                state,
                "Multimodal",
                started,
                f"Analyzed {len(images)} selected image(s).",
                {"image_count": len(images)},
            ),
        }

    def _reason_node(self, state: AgentWorkflowState) -> dict[str, object]:
        started = perf_counter()
        plan = state["plan"]
        try:
            result = self.reasoner.reason(
                state["question"],
                plan,
                evidence=state.get("evidence", []),
                images=state.get("observations", []),
                history=state.get("history", []),
                mode=state.get("mode", "hybrid"),
            )
        except Exception as error:
            self._record_node_failure(state, "Reasoning", started, error)
            raise
        return {
            "result": result,
            "traces": self._append_trace(
                state,
                "Reasoning",
                started,
                f"Checked citations and {len(result.task_outcomes)} task outcome(s).",
                {
                    "task_count": len(result.task_outcomes),
                    "citation_count": len(result.citations),
                },
            ),
        }

    def _output_guardrail_node(
        self,
        state: AgentWorkflowState,
    ) -> dict[str, object]:
        started = perf_counter()
        available_evidence = self._available_evidence(state)
        decision = self.output_guardrail.inspect(
            state["result"],
            available_evidence,
        )
        status = "failed" if decision.blocked else "completed"
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        state["observation"].record_node(
            "Output guardrail",
            status,
            duration_ms,
            {"citation_count": len(decision.result.citations)},
        )
        detail = (
            "Response withheld by output safety checks."
            if decision.blocked
            else "Validated answer safety and source references."
        )
        return {
            "result": decision.result,
            "guardrail_blocked": decision.blocked,
            "traces": [
                *state.get("traces", []),
                WorkflowTraceEntry(
                    node="Output guardrail",
                    status=status,
                    duration_ms=duration_ms,
                    detail=detail,
                ),
            ],
        }

    def _prepare_retry_node(
        self,
        state: AgentWorkflowState,
    ) -> dict[str, object]:
        started = perf_counter()
        feedback = self._missing_evidence_gaps(state)
        return {
            "retry_count": state.get("retry_count", 0) + 1,
            "retry_feedback": feedback,
            "traces": self._append_trace(
                state,
                "Evidence recovery",
                started,
                f"Retrying evidence collection for {len(feedback)} task(s).",
                {"task_count": len(feedback)},
            ),
        }

    @staticmethod
    def _available_evidence(state: AgentWorkflowState) -> list[SourceEvidence]:
        """Return document and image evidence references available to the answer."""
        evidence = list(state.get("evidence", []))
        plan = state.get("plan")
        if plan is None:
            return evidence
        evidence.extend(
            SourceEvidence(
                reference=image.reference,
                task_id=task.task_id,
                source_type="images",
                source=mask_sensitive_identifiers(image.source),
                text=mask_sensitive_identifiers(
                    image.summary + "\n" + image.extracted_text
                ),
                chunk_number=1,
            )
            for task in plan.tasks
            if task.source == "images"
            for image in state.get("observations", [])
        )
        unique_evidence: dict[str, SourceEvidence] = {}
        for item in evidence:
            unique_evidence.setdefault(item.reference, item)
        return list(unique_evidence.values())

    @staticmethod
    def _missing_evidence_gaps(
        state: AgentWorkflowState,
    ) -> list[EvidenceGap]:
        """Identify only incomplete tasks whose assigned source returned no evidence."""
        result = state.get("result")
        plan = state.get("plan")
        if result is None or plan is None:
            return []
        incomplete_ids = {
            outcome.task_id
            for outcome in result.task_outcomes
            if outcome.status == "incomplete"
        }
        document_evidence = state.get("evidence", [])
        observations = state.get("observations", [])
        gaps: list[EvidenceGap] = []
        for task in plan.tasks:
            if task.task_id not in incomplete_ids:
                continue
            if task.source == "documents" and not any(
                item.task_id == task.task_id for item in document_evidence
            ):
                reason = next(
                    (
                        outcome.reason
                        for outcome in result.task_outcomes
                        if outcome.task_id == task.task_id
                    ),
                    "No document evidence was returned.",
                )
                gaps.append(
                    EvidenceGap(task.task_id, "documents", task.description, reason)
                )
            elif task.source == "images" and not observations:
                reason = next(
                    (
                        outcome.reason
                        for outcome in result.task_outcomes
                        if outcome.task_id == task.task_id
                    ),
                    "No image evidence was returned.",
                )
                gaps.append(
                    EvidenceGap(task.task_id, "images", task.description, reason)
                )
        return gaps

    @staticmethod
    def _route_after_planning(state: AgentWorkflowState) -> str:
        plan = state["plan"]
        if not plan.in_scope:
            return "reason"
        if any(task.source == "documents" for task in plan.tasks):
            return "retrieve"
        if (
            state.get("images")
            and any(task.source == "images" for task in plan.tasks)
        ):
            return "analyze_images"
        return "reason"

    @staticmethod
    def _route_after_retrieval(state: AgentWorkflowState) -> str:
        retry_feedback = state.get("retry_feedback", [])
        if retry_feedback:
            if any(item.source == "images" for item in retry_feedback):
                return "analyze_images"
            return "reason"
        has_image_task = any(
            task.source == "images" for task in state["plan"].tasks
        )
        if has_image_task and state.get("images"):
            return "analyze_images"
        return "reason"

    @staticmethod
    def _route_after_output_guardrail(state: AgentWorkflowState) -> str:
        if state.get("guardrail_blocked", False):
            return "done"
        if state.get("retry_count", 0) >= MAX_EVIDENCE_RECOVERY_RETRIES:
            return "done"
        return (
            "retry"
            if AgentWorkflow._missing_evidence_gaps(state)
            else "done"
        )

    @staticmethod
    def _route_after_retry_preparation(state: AgentWorkflowState) -> str:
        feedback = state.get("retry_feedback", [])
        if any(item.source == "documents" for item in feedback):
            return "retrieve"
        if any(item.source == "images" for item in feedback):
            return "analyze_images"
        return "reason"

    def _append_trace(
        self,
        state: AgentWorkflowState,
        node: str,
        started: float,
        detail: str,
        metrics: dict[str, int],
    ) -> list[WorkflowTraceEntry]:
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        state["observation"].record_node(
            node,
            "completed",
            duration_ms,
            metrics,
        )
        return [
            *state.get("traces", []),
            WorkflowTraceEntry(
                node=node,
                status="completed",
                duration_ms=duration_ms,
                detail=detail,
            ),
        ]

    @staticmethod
    def _record_node_failure(
        state: AgentWorkflowState,
        node: str,
        started: float,
        error: BaseException,
    ) -> None:
        state["observation"].record_node(
            node,
            "failed",
            max(0, round((perf_counter() - started) * 1000)),
            error=error,
        )
