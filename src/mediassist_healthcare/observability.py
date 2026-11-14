"""Emit privacy-minimized application logs and optional LangSmith traces."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any

from langsmith import Client
from langsmith.run_trees import RunTree

from mediassist_healthcare.agent_models import AgentWorkflowResult
from mediassist_healthcare.settings import (
    get_langsmith_project_name,
    langsmith_tracing_is_enabled,
)

_LOGGER = logging.getLogger("mediassist_healthcare.observability")
_SAFE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SAFE_ROUTE_PATTERN = re.compile(r"^/[A-Za-z0-9_{}./-]{1,160}$")
_SAFE_LOG_FIELDS = {
    "event",
    "trace_id",
    "node",
    "status",
    "duration_ms",
    "retrieval_mode",
    "image_count",
    "task_count",
    "citation_count",
    "evidence_count",
    "exception_type",
    "provider_status",
    "provider_code",
    "request_id",
    "method",
    "route",
    "http_status",
}
_WARNING_EVENTS = {
    "workflow.failed",
    "workflow.local_dependency_failed",
    "http.request_failed",
    "http.processing_failed",
    "langsmith.publish_failed",
}


def safe_exception_fields(error: BaseException) -> dict[str, int | str]:
    """Return exception type and safe provider codes without exception text."""
    root = error
    while root.__cause__ is not None:
        root = root.__cause__

    fields: dict[str, int | str] = {"exception_type": type(root).__name__}
    status_code = getattr(root, "status_code", None)
    if isinstance(status_code, int):
        fields["provider_status"] = status_code
    code = getattr(root, "code", None)
    if isinstance(code, str) and _SAFE_CODE_PATTERN.fullmatch(code):
        fields["provider_code"] = code
    return fields


def log_safe_event(
    logger: logging.Logger,
    event: str,
    **fields: object,
) -> None:
    """Write a JSON log event containing only allowlisted primitive metadata."""
    record: dict[str, str | int] = {"event": event}
    for key, value in fields.items():
        if key not in _SAFE_LOG_FIELDS or key == "event":
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            record[key] = value
        elif isinstance(value, str) and _SAFE_CODE_PATTERN.fullmatch(value):
            record[key] = value[:120]
        elif key == "route" and isinstance(value, str) and _SAFE_ROUTE_PATTERN.fullmatch(value):
            record[key] = value
    level = logging.WARNING if event in _WARNING_EVENTS else logging.INFO
    logger.log(level, "%s", json.dumps(record, sort_keys=True))


class WorkflowObservation:
    """Collect safe local events and prepare an optional metadata-only trace."""

    def __init__(
        self,
        observer: WorkflowObserver,
        retrieval_mode: str,
        image_count: int,
    ) -> None:
        self.observer = observer
        self.trace_id = str(uuid.uuid4())
        self.retrieval_mode = retrieval_mode
        self.image_count = image_count
        self.root: RunTree | None = None
        client = observer._get_client()
        if client is not None:
            self.root = RunTree(
                name="MediAssist workflow",
                run_type="chain",
                inputs={"workflow": "mediassist-agent-workflow"},
                extra={
                    "metadata": {
                        "phase": 25,
                        "retrieval_mode": retrieval_mode,
                        "image_count": image_count,
                    }
                },
                project_name=observer.project_name,
                ls_client=client,
            )
        log_safe_event(
            _LOGGER,
            "workflow.started",
            trace_id=self.trace_id,
            retrieval_mode=retrieval_mode,
            image_count=image_count,
        )

    def record_node(
        self,
        node: str,
        status: str,
        duration_ms: int,
        metrics: dict[str, int] | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Record a node with its fixed label, duration, and numeric counts."""
        safe_metrics = {
            key: value
            for key, value in (metrics or {}).items()
            if key in {"task_count", "citation_count", "evidence_count", "image_count"}
            and isinstance(value, int)
            and not isinstance(value, bool)
        }
        fields: dict[str, object] = {
            "trace_id": self.trace_id,
            "node": node,
            "status": status,
            "duration_ms": max(duration_ms, 0),
            **safe_metrics,
        }
        if error is not None:
            fields.update(safe_exception_fields(error))
        log_safe_event(_LOGGER, "workflow.node", **fields)

        if self.root is None:
            return
        try:
            metadata: dict[str, int | str] = {
                "node": node,
                "status": status,
                "duration_ms": max(duration_ms, 0),
                **safe_metrics,
            }
            if error is not None:
                metadata["exception_type"] = safe_exception_fields(error)[
                    "exception_type"
                ]
            child = self.root.create_child(
                name=node,
                run_type="chain",
                inputs={"node": node},
                extra={"metadata": metadata},
            )
            child.end(
                outputs={
                    "status": status,
                    "duration_ms": max(duration_ms, 0),
                    **safe_metrics,
                    **(
                        {"exception_type": safe_exception_fields(error)["exception_type"]}
                        if error is not None
                        else {}
                    ),
                }
            )
        except Exception as telemetry_error:
            self.observer._log_telemetry_failure(telemetry_error)
            self.root = None

    def finish(
        self,
        result: AgentWorkflowResult | None = None,
        error: BaseException | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Close the workflow and submit only aggregate metadata to LangSmith."""
        output: dict[str, Any] = {
            "status": result.status if result is not None else "failed",
            "duration_ms": max(duration_ms, 0),
        }
        if result is not None:
            output.update(
                task_count=len(result.task_outcomes),
                citation_count=len(result.citations),
            )
        elif error is not None:
            output["exception_type"] = safe_exception_fields(error)["exception_type"]

        log_fields: dict[str, object] = {
            "trace_id": self.trace_id,
            "status": output["status"],
            "duration_ms": output["duration_ms"],
        }
        for metric in ("task_count", "citation_count"):
            if metric in output:
                log_fields[metric] = output[metric]
        if error is not None:
            log_fields.update(safe_exception_fields(error))
        log_safe_event(_LOGGER, "workflow.finished", **log_fields)

        if self.root is None:
            return
        try:
            metadata = self.root.extra.setdefault("metadata", {})
            metadata.update(output)
            if error is not None:
                metadata["exception_type"] = safe_exception_fields(error)[
                    "exception_type"
                ]
            self.root.end(outputs=output)
            self.root.post(exclude_child_runs=False)
        except Exception as telemetry_error:
            self.observer._log_telemetry_failure(telemetry_error)
            self.root = None


class WorkflowObserver:
    """Create local workflow events and opt-in metadata-only LangSmith traces."""

    def __init__(
        self,
        enabled: bool | None = None,
        client: Client | None = None,
        project_name: str | None = None,
    ) -> None:
        self.enabled = (
            langsmith_tracing_is_enabled() if enabled is None else enabled
        )
        self.project_name = project_name or get_langsmith_project_name()
        self._client = client
        self._client_checked = client is not None

    def start(self, retrieval_mode: str, image_count: int) -> WorkflowObservation:
        """Begin one observed request with no account or prompt identifiers."""
        return WorkflowObservation(self, retrieval_mode, image_count)

    def _get_client(self) -> Client | None:
        if not self.enabled:
            return None
        if self._client_checked:
            return self._client
        self._client_checked = True
        if not os.getenv("LANGSMITH_API_KEY"):
            log_safe_event(_LOGGER, "langsmith.disabled", status="missing_api_key")
            return None

        try:
            self._client = Client(
                timeout_ms=(2_000, 2_000),
                auto_batch_tracing=False,
                hide_inputs=True,
                hide_outputs=True,
            )
        except Exception as error:
            self._log_telemetry_failure(error)
        return self._client

    @staticmethod
    def _log_telemetry_failure(error: BaseException) -> None:
        fields = safe_exception_fields(error)
        log_safe_event(
            _LOGGER,
            "langsmith.publish_failed",
            exception_type=fields["exception_type"],
            provider_status=fields.get("provider_status", 0),
            provider_code=fields.get("provider_code", ""),
        )
