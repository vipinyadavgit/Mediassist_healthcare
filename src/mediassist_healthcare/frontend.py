"""Render the MediAssist Streamlit frontend and connect it to the FastAPI backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Literal, Sequence

import altair as alt
import streamlit as st

from mediassist_healthcare.api_client import (
    APIClientError,
    auth_error_message,
    ask_backend,
    delete_source as delete_backend_source,
    list_sources,
    login_user,
    logout_user,
    signup_user,
    upload_source,
)
from mediassist_healthcare.auth import validate_password
from mediassist_healthcare.settings import get_api_base_url

MAX_VISIBLE_EXCHANGES = 5
MAX_DASHBOARD_RECORDS = 200
DOCUMENT_TYPES = ["pdf", "docx", "txt"]
IMAGE_TYPES = ["png", "jpg", "jpeg", "webp"]
UPLOAD_TYPES = [*DOCUMENT_TYPES, *IMAGE_TYPES]
DASHBOARD_SOURCE_LABELS = {
    "documents": "Documents",
    "images": "Images",
    "mcp": "MCP",
}


@dataclass(frozen=True)
class ChatExchange:
    """Keep one user question paired with its assistant response."""

    question: str
    answer: str
    citations: list[dict[str, object]] = field(default_factory=list)
    status: str = "answered"
    tasks: list[dict[str, str]] = field(default_factory=list)
    traces: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class SourceFile:
    """Store the display details for a file listed in the frontend sources."""

    file_id: str
    name: str
    size_bytes: int
    kind: str


# Map a public backend source record into the UI's display model.
def add_source_file(
    sources: Sequence[SourceFile],
    file_id: str,
    name: str,
    size_bytes: int,
    kind: str,
) -> list[SourceFile]:
    """Return a new source list containing one backend-confirmed upload."""
    return [*sources, SourceFile(file_id, name, size_bytes, kind)]


# Remove a selected file from the frontend's visible source list.
def remove_source_file(
    sources: Sequence[SourceFile],
    file_id: str,
) -> list[SourceFile]:
    """Return the source list without the selected file."""
    return [source for source in sources if source.file_id != file_id]


# Determine the backend upload route from a supported file's extension.
def source_kind_for_filename(filename: str) -> Literal["document", "image"]:
    """Return whether a supported upload is a document or image."""
    suffix = filename.rsplit(".", maxsplit=1)[-1].casefold()
    if "." not in filename:
        raise ValueError("The uploaded file must have a supported extension.")
    if suffix in DOCUMENT_TYPES:
        return "document"
    if suffix in IMAGE_TYPES:
        return "image"
    raise ValueError("Choose a supported document or image file.")


# Keep complete question/answer pairs and discard the oldest pair first.
def keep_recent_exchanges(
    exchanges: Sequence[ChatExchange],
) -> list[ChatExchange]:
    """Return at most the latest five exchanges in FIFO order."""
    return list(exchanges[-MAX_VISIBLE_EXCHANGES:])


def build_dashboard_metrics(
    runs: Sequence[dict[str, object]],
) -> dict[str, object]:
    """Summarize content-free workflow records for the current UI session."""
    status_counts: dict[str, int] = {}
    source_counts = {"documents": 0, "images": 0, "mcp": 0}
    task_source_counts = {
        source: {"completed": 0, "incomplete": 0}
        for source in ("documents", "images", "mcp")
    }
    step_durations: dict[str, list[int]] = {}
    durations: list[int] = []
    duration_trend: list[dict[str, object]] = []
    citations = 0
    completed_tasks = 0
    total_tasks = 0
    for run_number, run in enumerate(runs, start=1):
        status = str(run.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        duration = run.get("duration_ms", 0)
        if isinstance(duration, int):
            safe_duration = max(0, duration)
            durations.append(safe_duration)
            duration_trend.append(
                {
                    "run": run_number,
                    "seconds": round(safe_duration / 1000, 3),
                    "status": status,
                }
            )
        citations_value = run.get("citations", [])
        if isinstance(citations_value, list):
            citations += len(citations_value)
            for citation in citations_value:
                if isinstance(citation, dict):
                    source_type = citation.get("source_type")
                    if isinstance(source_type, str) and source_type in source_counts:
                        source_counts[source_type] += 1
        tasks_value = run.get("tasks", [])
        if isinstance(tasks_value, list):
            for task in tasks_value:
                if not isinstance(task, dict):
                    continue
                task_status = task.get("status")
                task_source = task.get("source")
                if (
                    isinstance(task_status, str)
                    and task_status in {"completed", "incomplete"}
                    and isinstance(task_source, str)
                    and task_source in task_source_counts
                ):
                    task_source_counts[task_source][task_status] += 1
                    completed_tasks += task_status == "completed"
                    total_tasks += 1
        traces_value = run.get("traces", [])
        if isinstance(traces_value, list):
            for trace in traces_value:
                if not isinstance(trace, dict):
                    continue
                node = trace.get("node")
                duration_ms = trace.get("duration_ms")
                if (
                    isinstance(node, str)
                    and isinstance(duration_ms, int)
                    and duration_ms >= 0
                ):
                    step_durations.setdefault(node, []).append(duration_ms)

    return {
        "total_runs": len(runs),
        "answered_runs": status_counts.get("answered", 0),
        "status_counts": status_counts,
        "median_duration_ms": int(median(durations)) if durations else 0,
        "citation_count": citations,
        "source_counts": source_counts,
        "task_source_counts": task_source_counts,
        "completed_tasks": completed_tasks,
        "total_tasks": total_tasks,
        "duration_trend": duration_trend[-30:],
        "average_step_durations": {
            node: round(sum(values) / len(values))
            for node, values in step_durations.items()
        },
    }


def _dashboard_run(
    response: dict[str, object],
    duration_ms: int,
    timestamp: str | None = None,
) -> dict[str, object]:
    """Keep only dashboard-safe status, counts, and content-free node traces."""
    citations = response.get("citations", [])
    tasks = response.get("tasks", [])
    traces = response.get("traces", [])
    citation_items = citations if isinstance(citations, list) else []
    task_items = tasks if isinstance(tasks, list) else []
    trace_items = traces if isinstance(traces, list) else []
    safe_citations = [
        {"source_type": citation["source_type"]}
        for citation in citation_items
        if isinstance(citation, dict)
        and isinstance(citation.get("source_type"), str)
        and citation["source_type"] in {"documents", "images", "mcp"}
    ]
    safe_tasks = [
        {"status": task["status"], "source": task["source"]}
        for task in task_items
        if isinstance(task, dict)
        and isinstance(task.get("status"), str)
        and task["status"] in {"completed", "incomplete"}
        and isinstance(task.get("source"), str)
        and task["source"] in {"documents", "images", "mcp"}
    ]
    safe_traces = [
        {
            "node": trace["node"],
            "status": trace["status"],
            "duration_ms": trace["duration_ms"],
        }
        for trace in trace_items
        if isinstance(trace, dict)
        and isinstance(trace.get("node"), str)
        and trace.get("status") == "completed"
        and isinstance(trace.get("duration_ms"), int)
    ]
    return {
        "timestamp": timestamp or datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "status": response.get("status", "unknown"),
        "duration_ms": max(0, duration_ms),
        "citations": safe_citations,
        "tasks": safe_tasks,
        "traces": safe_traces,
    }


# Configure the page and keep colors readable in the light healthcare palette.
def _configure_page() -> None:
    st.set_page_config(
        page_title="MediAssist AI",
        page_icon="＋",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root {
            --mediassist-ink: #18312d;
            --mediassist-muted: #61736f;
            --mediassist-green: #167d68;
            --mediassist-green-dark: #106451;
            --mediassist-pale: #e8f3ef;
            --mediassist-border: #dce8e3;
        }
        .stApp {
            background:
                radial-gradient(ellipse at 86% 0%, #e8f4ef 0, transparent 32rem),
                #f5f8f7;
            color: var(--mediassist-ink);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #edf5f1 0%, #e5f0eb 100%);
            border-right: 1px solid var(--mediassist-border);
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--mediassist-ink);
        }
        [data-testid="stSidebar"] h1 {
            letter-spacing: -0.035em;
        }
        [data-testid="stFileUploader"] section {
            background: rgba(255, 255, 255, 0.78);
            border: 1px dashed #9bbcaf;
            border-radius: 0.85rem;
        }
        [data-testid="stFileUploader"] section > button {
            color: var(--mediassist-green-dark);
            border: 1px solid #b7d2c7;
            background: #f5faf7;
        }
        [data-testid="stFileUploader"] small,
        [data-testid="stFileUploader"] span {
            color: var(--mediassist-muted);
        }
        .stButton > button {
            border-radius: 0.7rem;
            font-weight: 600;
            transition: border-color 120ms ease, background 120ms ease;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: var(--mediassist-green);
            border-color: var(--mediassist-green);
            color: #ffffff;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
            background: var(--mediassist-green-dark);
            border-color: var(--mediassist-green-dark);
        }
        [data-testid="stSidebar"] .stButton > button:not([kind="primary"]) {
            background: rgba(255, 255, 255, 0.7);
            color: var(--mediassist-muted);
        }
        [data-testid="stChatMessage"] {
            background: #ffffff;
            border: 1px solid var(--mediassist-border);
            border-radius: 1rem;
            padding: 0.55rem 1rem;
            box-shadow: 0 4px 16px rgba(27, 62, 51, 0.035);
        }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background: #edf6f2;
        }
        [data-testid="stChatInput"] {
            border-color: #cbdcd4;
            border-radius: 1rem;
            background: #ffffff;
            box-shadow: 0 8px 26px rgba(27, 62, 51, 0.08);
        }
        [data-testid="stChatInput"] textarea {
            color: var(--mediassist-ink);
        }
        .mediassist-subtitle {
            color: var(--mediassist-muted);
            font-size: 1.04rem;
            margin: -0.45rem 0 1.2rem;
        }
        .mediassist-kicker {
            color: var(--mediassist-green);
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            margin-bottom: 0.65rem;
            text-transform: uppercase;
        }
        .mediassist-note {
            background: #edf5f1;
            border: 1px solid #dce8e3;
            border-radius: 0.75rem;
            color: #526761;
            font-size: 0.82rem;
            line-height: 1.5;
            padding: 0.8rem 0.9rem;
        }
        .mediassist-empty {
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid var(--mediassist-border);
            border-radius: 1rem;
            margin: 2rem 0 1.25rem;
            padding: 1.6rem 1.75rem;
        }
        .mediassist-dashboard-hero {
            background: linear-gradient(120deg, #ffffff 0%, #eaf5f0 100%);
            border: 1px solid var(--mediassist-border);
            border-radius: 1.1rem;
            margin: 0.6rem 0 1.2rem;
            padding: 1.35rem 1.55rem;
        }
        .mediassist-dashboard-hero h2 {
            color: var(--mediassist-ink);
            font-size: 1.35rem;
            letter-spacing: -0.025em;
            margin: 0 0 0.35rem;
        }
        .mediassist-dashboard-hero p {
            color: var(--mediassist-muted);
            margin: 0;
        }
        [data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.88);
            border: 1px solid var(--mediassist-border);
            border-radius: 0.9rem;
            box-shadow: 0 5px 18px rgba(27, 62, 51, 0.045);
            padding: 0.9rem 1rem;
        }
        [data-testid="stMetricLabel"] {
            color: var(--mediassist-muted);
        }
        [data-testid="stMetricValue"] {
            color: var(--mediassist-ink);
            font-weight: 700;
        }
        .mediassist-empty h3 {
            color: var(--mediassist-ink);
            font-size: 1.05rem;
            margin: 0 0 0.35rem;
        }
        .mediassist-empty p {
            color: var(--mediassist-muted);
            font-size: 0.92rem;
            margin: 0;
        }
        .mediassist-source-label {
            color: #61736f;
            font-size: 0.78rem;
            font-weight: 650;
            letter-spacing: 0.045em;
            text-transform: uppercase;
        }
        [data-testid="stMainBlockContainer"] {
            max-width: 1120px;
            padding-top: 2.4rem;
            padding-bottom: 2rem;
        }
        @media (max-width: 720px) {
            [data-testid="stMainBlockContainer"] {
                padding-top: 1.25rem;
                padding-bottom: 1rem;
            }
            [data-testid="stSidebar"] {
                min-width: 17rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# Initialize the source list and counters used by the frontend.
def _initialize_session() -> None:
    if "access_token" not in st.session_state:
        st.session_state.access_token = ""
    if "authenticated_user" not in st.session_state:
        st.session_state.authenticated_user = None
    if "backend_session_id" not in st.session_state:
        st.session_state.backend_session_id = ""
    if "sources" not in st.session_state:
        st.session_state.sources = []
    if "chat_exchanges" not in st.session_state:
        st.session_state.chat_exchanges = []
    if "workflow_runs" not in st.session_state:
        st.session_state.workflow_runs = []
    if "upload_slot" not in st.session_state:
        st.session_state.upload_slot = 0


# Refresh backend-persisted file names for the current browser session.
def _refresh_sources() -> None:
    try:
        sources = list_sources(
            get_api_base_url(),
            st.session_state.backend_session_id,
            st.session_state.access_token,
        )
    except APIClientError as error:
        st.session_state.backend_error = str(error)
        return

    st.session_state.sources = [
        add_source_file(
            [],
            item["file_id"],
            item["name"],
            item["size_bytes"],
            item["kind"],
        )[0]
        for item in sources
    ]
    st.session_state.backend_error = ""


# Upload one document or image and display all session sources in one list.
def _render_sources() -> None:
    st.markdown("#### Upload documents or images")
    st.caption("Add one file at a time. Remove any source whenever you like.")
    selected_file = st.file_uploader(
        "Select one document or image",
        type=UPLOAD_TYPES,
        accept_multiple_files=False,
        key=f"source_uploader_{st.session_state.upload_slot}",
        label_visibility="collapsed",
    )

    if st.button(
        "Add to sources",
        key="source_add",
        use_container_width=True,
        type="primary",
    ):
        if selected_file is None:
            st.warning("Choose a document or image before adding it.")
        else:
            try:
                kind = source_kind_for_filename(selected_file.name)
                uploaded = upload_source(
                    get_api_base_url(),
                    st.session_state.backend_session_id,
                    st.session_state.access_token,
                    kind,
                    selected_file.name,
                    selected_file.getvalue(),
                    selected_file.type or "application/octet-stream",
                )
            except ValueError as error:
                st.error(str(error))
            except APIClientError as error:
                st.error(str(error))
            else:
                st.session_state.sources = add_source_file(
                    st.session_state.sources,
                    uploaded["file_id"],
                    uploaded["name"],
                    uploaded["size_bytes"],
                    uploaded["kind"],
                )
                st.session_state.upload_slot += 1
                st.toast(uploaded["message"], icon="✅")
                st.rerun()

    st.markdown(
        '<div class="mediassist-source-label">Sources</div>',
        unsafe_allow_html=True,
    )
    sources: list[SourceFile] = st.session_state.sources
    if not sources:
        st.caption("Your added files will appear here.")
        return

    for source in sources:
        name_column, remove_column = st.columns([4, 1], vertical_alignment="center")
        with name_column:
            source_type = "Image" if source.kind == "image" else "Document"
            st.text(f"{source_type}: {source.name}")
            st.caption(f"{source.size_bytes / 1024:.0f} KB")
        with remove_column:
            if st.button(
                "✕",
                key=f"source_remove_{source.file_id}",
                help=f"Remove {source.name} from sources",
            ):
                try:
                    delete_backend_source(
                        get_api_base_url(),
                        st.session_state.backend_session_id,
                        st.session_state.access_token,
                        source.file_id,
                    )
                except APIClientError as error:
                    st.error(str(error))
                else:
                    st.session_state.sources = remove_source_file(
                        sources,
                        source.file_id,
                    )
                    st.rerun()


# Render the reference slide's separate document and image source sections.
def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("# MediAssist")
        st.markdown(
            '<p class="mediassist-subtitle">Healthcare knowledge assistant</p>',
            unsafe_allow_html=True,
        )
        user = st.session_state.authenticated_user
        st.caption(f"Signed in as **{user['first_name']} {user['last_name']}**")
        if st.button("Log out", key="logout", use_container_width=True):
            try:
                logout_user(
                    get_api_base_url(),
                    st.session_state.access_token,
                )
            except APIClientError as error:
                st.session_state.auth_message = (
                    f"Signed out locally. The server session could not be revoked: {error}"
                )
            else:
                st.session_state.auth_message = "You have been signed out."
            st.session_state.access_token = ""
            st.session_state.authenticated_user = None
            st.session_state.backend_session_id = ""
            st.session_state.sources = []
            st.session_state.chat_exchanges = []
            st.session_state.workflow_runs = []
            st.rerun()
        st.markdown("#### Knowledge sources")
        _render_sources()
        st.divider()
        if st.session_state.backend_error:
            st.error(st.session_state.backend_error)
        else:
            st.markdown(
                '<div class="mediassist-note"><strong>API connected</strong><br>'
                "Documents are indexed for this session. Image analysis requires "
                "backend enablement and your per-request approval.</div>",
                unsafe_allow_html=True,
            )


# Save the authenticated identity and use its stable ID for source ownership.
def _start_authenticated_session(auth: dict[str, object]) -> None:
    user = auth["user"]
    if not isinstance(user, dict):
        raise APIClientError("The backend returned an invalid user profile.")
    access_token = auth.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise APIClientError("The backend did not return a valid login session.")
    user_id = user.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise APIClientError("The backend profile does not include an account ID.")
    st.session_state.access_token = access_token
    st.session_state.authenticated_user = user
    st.session_state.backend_session_id = user_id
    st.session_state.sources = []
    st.session_state.chat_exchanges = []
    st.session_state.workflow_runs = []
    st.session_state.backend_error = ""
    st.session_state.auth_message = ""


# Render login and signup before allowing access to source/chat screens.
def _render_auth_screen() -> None:
    if st.session_state.pop("signup_completed", False):
        st.session_state.auth_mode = "Log in"
        st.session_state.login_username = st.session_state.pop(
            "new_account_username",
            "",
        )
        st.session_state.signup_password = ""
        st.session_state.signup_confirm_password = ""
        st.session_state.signup_first_name = ""
        st.session_state.signup_last_name = ""
        st.session_state.signup_username = ""

    st.markdown(
        '<div class="mediassist-kicker">MediAssist AI · Secure sign-in</div>',
        unsafe_allow_html=True,
    )
    st.title("Welcome to MediAssist")
    st.markdown(
        '<p class="mediassist-subtitle">Sign in to your account or create '
        "one to continue.</p>",
        unsafe_allow_html=True,
    )
    auth_message = st.session_state.get("auth_message")
    if auth_message:
        st.info(auth_message)
    if st.session_state.get("backend_error"):
        st.error(st.session_state.backend_error)

    auth_mode = st.radio(
        "Account access",
        ["Log in", "Create account"],
        key="auth_mode",
        horizontal=True,
        label_visibility="collapsed",
    )
    if auth_mode == "Log in":
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input(
                "Password",
                type="password",
                key="login_password",
                placeholder="Enter your password",
            )
            submitted = st.form_submit_button(
                "Log in",
                type="primary",
                use_container_width=True,
            )
        if submitted:
            try:
                auth = login_user(get_api_base_url(), username, password)
                _start_authenticated_session(auth)
            except APIClientError as error:
                st.error(auth_error_message(error, "login"))
            else:
                st.rerun()

    else:
        with st.form("signup_form"):
            first_name = st.text_input("First name", key="signup_first_name")
            last_name = st.text_input("Last name", key="signup_last_name")
            username = st.text_input("Username", key="signup_username")
            password = st.text_input(
                "Create password",
                type="password",
                key="signup_password",
                placeholder="Example: Snooker@147",
            )
            st.caption(
                "Use 8–128 characters. Start with an uppercase letter and include "
                "at least one lowercase letter and one number. Special characters "
                "such as @ are allowed."
            )
            confirm_password = st.text_input(
                "Confirm password",
                type="password",
                key="signup_confirm_password",
                placeholder="Re-enter your password",
            )
            submitted = st.form_submit_button(
                "Create account",
                type="primary",
                use_container_width=True,
            )
        if submitted:
            try:
                validate_password(password)
                if password != confirm_password:
                    raise ValueError(
                        "Passwords do not match. Enter the same password in both fields."
                    )
                signup_user(
                    get_api_base_url(),
                    first_name,
                    last_name,
                    username,
                    password,
                    confirm_password,
                )
            except APIClientError as error:
                st.error(auth_error_message(error, "signup"))
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state.auth_message = (
                    "Your account has been created. Please log in with your new "
                    "username and password."
                )
                st.session_state.new_account_username = username
                st.session_state.signup_completed = True
                st.rerun()


# Display the latest five complete question/answer pairs in FIFO order.
def _render_chat_history() -> None:
    exchanges: list[ChatExchange] = keep_recent_exchanges(
        st.session_state.chat_exchanges
    )
    st.session_state.chat_exchanges = exchanges
    if not exchanges:
        st.markdown(
            '<div class="mediassist-empty"><h3>Start a conversation</h3>'
            "<p>Ask a question about MediAssist healthcare policies, SOPs, "
            "or hospital operations.</p></div>",
            unsafe_allow_html=True,
        )
        return

    for exchange in exchanges:
        with st.chat_message("user"):
            st.markdown(exchange.question)
        with st.chat_message("assistant"):
            st.markdown(exchange.answer)
            if exchange.status == "insufficient_evidence":
                st.caption("No supporting passages were found in this session's documents.")
            elif exchange.status == "partial":
                st.caption("Some planned tasks could not be completed; see the details below.")
            elif exchange.status == "out_of_scope":
                st.caption("This question is outside MediAssist's supported topics.")
            for citation in exchange.citations:
                if citation.get("source_type") == "mcp":
                    st.caption(
                        f"[{citation['reference']}] {citation['source']} · "
                        "read-only database"
                    )
                elif citation.get("source_type") == "images":
                    st.caption(f"[{citation['reference']}] {citation['source']} · image")
                else:
                    st.caption(
                        f"[{citation['reference']}] {citation['source']} · "
                        f"chunk {citation['chunk_number']}"
                    )
            for task in exchange.tasks:
                status_icon = "✓" if task["status"] == "completed" else "!"
                st.caption(
                    f"{status_icon} {task['description']} — {task['status']}: "
                    f"{task['reason']}"
                )
            if exchange.traces:
                with st.expander("Workflow trace"):
                    for trace in exchange.traces:
                        st.caption(
                            f"{trace.get('node', 'Agent')} · "
                            f"{trace.get('duration_ms', 0)} ms · "
                            f"{trace.get('detail', '')}"
                        )


def _render_dashboard() -> None:
    """Show session-only workflow activity without retaining prompt content."""
    runs: list[dict[str, object]] = st.session_state.workflow_runs
    metrics = build_dashboard_metrics(runs)
    st.markdown(
        '<div class="mediassist-kicker">MediAssist AI · SESSION INSIGHTS</div>'
        '<div class="mediassist-dashboard-hero"><h2>Workflow analytics</h2>'
        "<p>Understand response quality, source coverage, and processing time "
        "for this session. Prescription text, patient identifiers, and prompts "
        "are not shown or stored in these charts.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Private to your signed-in UI session · Cleared when you log out or this "
        "session ends · Maximum 200 recent runs"
    )
    if not runs:
        st.info(
            "No workflow activity yet. Ask a question in Chat to see response "
            "status, agent traces, timings, and citation metrics here."
        )
        return

    total_runs = int(metrics["total_runs"])
    answered_runs = int(metrics["answered_runs"])
    answered_percent = round(answered_runs / total_runs * 100) if total_runs else 0
    task_total = int(metrics["total_tasks"])
    task_completed = int(metrics["completed_tasks"])
    task_percent = round(task_completed / task_total * 100) if task_total else 0
    duration_seconds = int(metrics["median_duration_ms"]) / 1000
    metric_columns = st.columns(4)
    metric_columns[0].metric("Workflows", total_runs)
    metric_columns[1].metric("Fully answered", f"{answered_percent}%")
    metric_columns[2].metric("Median response time", f"{duration_seconds:.1f} s")
    metric_columns[3].metric(
        "Tasks completed",
        f"{task_completed}/{task_total}",
        f"{task_percent}% completion" if task_total else "No planned tasks yet",
    )

    chart_columns = st.columns(2)
    status_counts = metrics["status_counts"]
    with chart_columns[0]:
        st.markdown("#### Response outcomes")
        st.caption("How each workflow concluded")
        if isinstance(status_counts, dict) and status_counts:
            outcome_data = [
                {"outcome": outcome.replace("_", " ").title(), "runs": count}
                for outcome, count in status_counts.items()
            ]
            outcome_chart = (
                alt.Chart(alt.Data(values=outcome_data))
                .mark_bar(cornerRadiusEnd=6)
                .encode(
                    x=alt.X("runs:Q", title="Workflows", scale=alt.Scale(domainMin=0)),
                    y=alt.Y("outcome:N", title=None, sort="-x"),
                    color=alt.Color(
                        "outcome:N",
                        title=None,
                        scale=alt.Scale(
                            domain=[
                                "Answered",
                                "Partial",
                                "Insufficient Evidence",
                                "Out Of Scope",
                                "Failed",
                            ],
                            range=["#167d68", "#d99b3d", "#bf625a", "#748b97", "#59636b"],
                        ),
                        legend=None,
                    ),
                    tooltip=["outcome:N", "runs:Q"],
                )
                .properties(height=220)
                .configure_view(stroke=None)
                .configure_axis(
                    gridColor="#edf2ef",
                    domainColor="#dce8e3",
                    labelColor="#526761",
                    titleColor="#526761",
                )
            )
            st.altair_chart(outcome_chart, width="stretch", theme=None)
    with chart_columns[1]:
        st.markdown("#### Response-time trend")
        st.caption("Most recent 30 workflows · seconds")
        duration_trend = metrics["duration_trend"]
        if isinstance(duration_trend, list) and duration_trend:
            duration_chart = (
                alt.Chart(alt.Data(values=duration_trend))
                .mark_line(
                    color="#167d68",
                    point=alt.OverlayMarkDef(filled=True, size=48),
                    strokeWidth=2.5,
                )
                .encode(
                    x=alt.X("run:Q", title="Workflow, oldest to newest"),
                    y=alt.Y(
                        "seconds:Q",
                        title="Seconds",
                        scale=alt.Scale(zero=True),
                    ),
                    tooltip=[
                        alt.Tooltip("run:Q", title="Workflow"),
                        alt.Tooltip("seconds:Q", title="Duration", format=".3f"),
                        alt.Tooltip("status:N", title="Outcome"),
                    ],
                )
                .properties(height=220)
                .configure_view(stroke=None)
                .configure_axis(
                    gridColor="#edf2ef",
                    domainColor="#dce8e3",
                    labelColor="#526761",
                    titleColor="#526761",
                )
            )
            st.altair_chart(duration_chart, width="stretch", theme=None)
        else:
            st.caption("No response-time samples are available yet.")

    st.markdown("#### Evidence and task coverage")
    coverage_columns = st.columns(2)
    source_counts = metrics["source_counts"]
    with coverage_columns[0]:
        st.caption("Validated citations by source type")
        if isinstance(source_counts, dict) and sum(source_counts.values()) > 0:
            source_data = [
                {
                    "source": DASHBOARD_SOURCE_LABELS[source],
                    "citations": count,
                }
                for source, count in source_counts.items()
                if count
            ]
            source_chart = (
                alt.Chart(alt.Data(values=source_data))
                .mark_bar(cornerRadiusEnd=6)
                .encode(
                    x=alt.X("citations:Q", title="Citations", scale=alt.Scale(domainMin=0)),
                    y=alt.Y("source:N", title=None, sort="-x"),
                    color=alt.Color(
                        "source:N",
                        title=None,
                        scale=alt.Scale(
                            domain=["Documents", "Images", "MCP"],
                            range=["#167d68", "#6f9eae", "#d99b3d"],
                        ),
                        legend=None,
                    ),
                    tooltip=["source:N", "citations:Q"],
                )
                .properties(height=190)
                .configure_view(stroke=None)
                .configure_axis(
                    gridColor="#edf2ef",
                    domainColor="#dce8e3",
                    labelColor="#526761",
                    titleColor="#526761",
                )
            )
            st.altair_chart(source_chart, width="stretch", theme=None)
        else:
            st.caption("No cited sources yet.")
    with coverage_columns[1]:
        st.caption("Planned tasks by source and completion")
        task_source_counts = metrics["task_source_counts"]
        task_data = [
            {
                "source": DASHBOARD_SOURCE_LABELS[source],
                "status": status.title(),
                "tasks": count,
            }
            for source, counts in task_source_counts.items()
            for status, count in counts.items()
            if count
        ]
        if task_data:
            task_chart = (
                alt.Chart(alt.Data(values=task_data))
                .mark_bar(cornerRadius=4)
                .encode(
                    x=alt.X("source:N", title=None),
                    y=alt.Y("tasks:Q", title="Tasks", stack="zero"),
                    color=alt.Color(
                        "status:N",
                        title="Task status",
                        scale=alt.Scale(
                            domain=["Completed", "Incomplete"],
                            range=["#167d68", "#d99b3d"],
                        ),
                    ),
                    tooltip=["source:N", "status:N", "tasks:Q"],
                )
                .properties(height=190)
                .configure_view(stroke=None)
                .configure_axis(
                    gridColor="#edf2ef",
                    domainColor="#dce8e3",
                    labelColor="#526761",
                    titleColor="#526761",
                )
                .configure_legend(labelColor="#526761", titleColor="#526761")
            )
            st.altair_chart(task_chart, width="stretch", theme=None)
        else:
            st.caption("No planned tasks are available yet.")

    st.markdown("#### Agent execution time")
    st.caption("Average processing time per workflow step · milliseconds")
    step_durations = metrics["average_step_durations"]
    if isinstance(step_durations, dict) and step_durations:
        agent_data = [
            {"agent": agent, "milliseconds": duration}
            for agent, duration in step_durations.items()
        ]
        agent_chart = (
            alt.Chart(alt.Data(values=agent_data))
            .mark_bar(color="#77a995", cornerRadiusEnd=6)
            .encode(
                x=alt.X("milliseconds:Q", title="Average milliseconds"),
                y=alt.Y("agent:N", title=None, sort="-x"),
                tooltip=["agent:N", "milliseconds:Q"],
            )
            .properties(height=min(300, max(120, 32 * len(agent_data))))
            .configure_view(stroke=None)
            .configure_axis(
                gridColor="#edf2ef",
                domainColor="#dce8e3",
                labelColor="#526761",
                titleColor="#526761",
            )
        )
        st.altair_chart(agent_chart, width="stretch", theme=None)
    else:
        st.caption("No completed agent traces are available yet.")

    st.markdown("#### Recent workflows")
    with st.container(border=True):
        st.caption("Source names and clinical content are intentionally excluded.")
        st.dataframe(
            [
                {
                    "Time": run.get("timestamp"),
                    "Outcome": run.get("status"),
                    "Duration": f"{int(run.get('duration_ms', 0)) / 1000:.1f} s",
                    "Tasks": len(run.get("tasks", [])),
                    "Citations": len(run.get("citations", [])),
                    "Evidence": ", ".join(
                        sorted(
                            {
                                DASHBOARD_SOURCE_LABELS.get(
                                    str(citation.get("source_type", "")),
                                    "Other",
                                )
                                for citation in run.get("citations", [])
                                if isinstance(citation, dict)
                            }
                        )
                    )
                    or "None",
                }
                for run in reversed(runs)
            ],
            hide_index=True,
            width="stretch",
        )

    st.markdown("#### Workflow traces")
    for index, run in reversed(list(enumerate(runs, start=1))):
        run_traces = run.get("traces", [])
        with st.expander(
            f"Run {index} · {run.get('status', 'unknown')} · "
            f"{int(run.get('duration_ms', 0)) / 1000:.1f} s"
        ):
            if not isinstance(run_traces, list) or not run_traces:
                st.caption("No completed node trace was returned for this run.")
            else:
                for trace in run_traces:
                    if isinstance(trace, dict):
                        st.markdown(
                            f"**{trace.get('node', 'Agent')}** · "
                            f"{trace.get('status', 'unknown')} · "
                            f"{trace.get('duration_ms', 0)} ms"
                        )


# Submit a question with recent context and explicitly selected image inputs.
def _handle_question() -> None:
    sources: list[SourceFile] = st.session_state.sources
    image_sources = [source for source in sources if source.kind == "image"]
    selected_image_ids: list[str] = []
    if image_sources:
        selected_image_ids = st.multiselect(
            "Use uploaded images for this question",
            options=[source.file_id for source in image_sources],
            format_func=lambda source_id: next(
                source.name for source in image_sources if source.file_id == source_id
            ),
            key="selected_image_source_ids",
            max_selections=5,
        )
    external_image_approved = st.checkbox(
        "I confirm these images are authorized for processing by the configured "
        "external vision provider",
        key="external_image_approved",
        help=(
            "Image bytes are sent to the configured external vision provider only "
            "when the server also enables external image processing."
        ),
    )
    prompt = st.chat_input(
        "Ask about MediAssist policies, reports, or uploaded images...",
        accept_file="multiple",
        file_type=IMAGE_TYPES,
        max_upload_size=10,
    )
    if prompt is None:
        return

    if isinstance(prompt, str):
        question = prompt.strip()
        attachments = []
    else:
        question = prompt.text.strip()
        attachments = prompt.files
    if not question:
        st.warning("Add a question along with any image attachments.")
        return
    if len(attachments) + len(selected_image_ids) > 5:
        st.error("Use no more than five images per question.")
        return
    image_files = [
        (
            attachment.name,
            attachment.getvalue(),
            attachment.type or "application/octet-stream",
        )
        for attachment in attachments
    ]
    exchanges: list[ChatExchange] = keep_recent_exchanges(
        st.session_state.chat_exchanges
    )
    history = [
        {"question": exchange.question, "answer": exchange.answer}
        for exchange in exchanges
    ]

    started_at = datetime.now().astimezone()
    with st.spinner("Planning tasks and gathering source evidence…"):
        try:
            response = ask_backend(
                get_api_base_url(),
                st.session_state.backend_session_id,
                st.session_state.access_token,
                question,
                image_source_ids=selected_image_ids,
                history=history,
                image_files=image_files,
                external_image_approved=external_image_approved,
            )
        except APIClientError as error:
            duration_ms = int(
                (datetime.now().astimezone() - started_at).total_seconds() * 1000
            )
            failed_run = _dashboard_run(
                {"status": "failed"},
                duration_ms,
                started_at.isoformat(timespec="seconds"),
            )
            st.session_state.workflow_runs = [
                *st.session_state.workflow_runs,
                failed_run,
            ][-MAX_DASHBOARD_RECORDS:]
            st.error(str(error))
            return

    duration_ms = int(
        (datetime.now().astimezone() - started_at).total_seconds() * 1000
    )
    dashboard_run = _dashboard_run(
        response,
        duration_ms,
        started_at.isoformat(timespec="seconds"),
    )
    st.session_state.workflow_runs = [
        *st.session_state.workflow_runs,
        dashboard_run,
    ][-MAX_DASHBOARD_RECORDS:]
    st.session_state.chat_exchanges = keep_recent_exchanges(
        [
            *exchanges,
            ChatExchange(
                question=question,
                answer=response["answer"],
                citations=response["citations"],
                status=response["status"],
                tasks=response.get("tasks", []),
                traces=response.get("traces", []),
            ),
        ]
    )
    st.rerun()


# Assemble the Streamlit interface and connect its actions to FastAPI.
def main() -> None:
    """Run the standalone Streamlit user interface."""
    _configure_page()
    _initialize_session()
    if not st.session_state.access_token:
        _render_auth_screen()
        return
    _refresh_sources()
    _render_sidebar()

    selected_page = st.radio(
        "Workspace",
        ["Chat", "Analytics dashboard"],
        horizontal=True,
        label_visibility="collapsed",
        key="workspace_page",
    )
    if selected_page == "Analytics dashboard":
        _render_dashboard()
        return

    st.markdown(
        '<div class="mediassist-kicker">MediAssist AI · Phase 11</div>',
        unsafe_allow_html=True,
    )
    st.title("Your healthcare knowledge assistant")
    st.markdown(
        '<p class="mediassist-subtitle">Ask about MediAssist policies, '
        "standard operating procedures, and hospital operations.</p>",
        unsafe_allow_html=True,
    )
    st.caption(f"Connected to the MediAssist API at {get_api_base_url()}.")
    _render_chat_history()
    _handle_question()


if __name__ == "__main__":
    main()
