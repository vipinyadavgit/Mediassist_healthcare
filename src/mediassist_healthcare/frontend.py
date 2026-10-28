"""Render the MediAssist Streamlit frontend and connect it to the Phase 12 API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
from uuid import uuid4

import streamlit as st

from mediassist_healthcare.api_client import (
    APIClientError,
    ask_backend,
    delete_source as delete_backend_source,
    list_sources,
    upload_source,
)
from mediassist_healthcare.settings import get_api_base_url

MAX_VISIBLE_EXCHANGES = 5
DOCUMENT_TYPES = ["pdf", "docx", "txt"]
IMAGE_TYPES = ["png", "jpg", "jpeg", "webp"]


@dataclass(frozen=True)
class ChatExchange:
    """Keep one user question paired with its assistant response."""

    question: str
    answer: str
    citations: list[dict[str, object]] = field(default_factory=list)
    status: str = "answered"


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


# Keep complete question/answer pairs and discard the oldest pair first.
def keep_recent_exchanges(
    exchanges: Sequence[ChatExchange],
) -> list[ChatExchange]:
    """Return at most the latest five exchanges in FIFO order."""
    return list(exchanges[-MAX_VISIBLE_EXCHANGES:])


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


# Initialize session-only lists and counters used by the frontend.
def _initialize_session() -> None:
    if "backend_session_id" not in st.session_state:
        st.session_state.backend_session_id = str(uuid4())
    if "document_sources" not in st.session_state:
        st.session_state.document_sources = []
    if "image_sources" not in st.session_state:
        st.session_state.image_sources = []
    if "chat_exchanges" not in st.session_state:
        st.session_state.chat_exchanges = []
    if "document_upload_slot" not in st.session_state:
        st.session_state.document_upload_slot = 0
    if "image_upload_slot" not in st.session_state:
        st.session_state.image_upload_slot = 0


# Refresh backend-persisted file names for the current browser session.
def _refresh_sources() -> None:
    try:
        sources = list_sources(
            get_api_base_url(),
            st.session_state.backend_session_id,
        )
    except APIClientError as error:
        st.session_state.backend_error = str(error)
        return

    st.session_state.document_sources = [
        add_source_file(
            [],
            item["file_id"],
            item["name"],
            item["size_bytes"],
            "document",
        )[0]
        for item in sources
        if item["kind"] == "document"
    ]
    st.session_state.image_sources = [
        add_source_file(
            [],
            item["file_id"],
            item["name"],
            item["size_bytes"],
            "image",
        )[0]
        for item in sources
        if item["kind"] == "image"
    ]
    st.session_state.backend_error = ""


# Add one file to the backend or remove its backend source and indexed chunks.
def _render_upload_section(
    title: str,
    section_key: str,
    accepted_types: list[str],
    source_state_key: str,
    slot_state_key: str,
    kind: str,
) -> None:
    st.markdown(f"### {title}")
    selected_file = st.file_uploader(
        f"Select one {title.lower()[:-1]} file",
        type=accepted_types,
        accept_multiple_files=False,
        key=f"{section_key}_uploader_{st.session_state[slot_state_key]}",
        label_visibility="collapsed",
    )

    if st.button(
        f"Add {title[:-1].lower()}",
        key=f"{section_key}_add",
        use_container_width=True,
        type="primary",
    ):
        if selected_file is None:
            st.warning(f"Choose a {title[:-1].lower()} before adding it.")
        else:
            try:
                uploaded = upload_source(
                    get_api_base_url(),
                    st.session_state.backend_session_id,
                    kind,
                    selected_file.name,
                    selected_file.getvalue(),
                    selected_file.type or "application/octet-stream",
                )
            except APIClientError as error:
                st.error(str(error))
            else:
                current_sources = st.session_state[source_state_key]
                st.session_state[source_state_key] = add_source_file(
                    current_sources,
                    uploaded["file_id"],
                    uploaded["name"],
                    uploaded["size_bytes"],
                    uploaded["kind"],
                )
                st.session_state[slot_state_key] += 1
                st.toast(uploaded["message"], icon="✅")
                st.rerun()

    st.markdown(
        '<div class="mediassist-source-label">Sources</div>',
        unsafe_allow_html=True,
    )
    sources: list[SourceFile] = st.session_state[source_state_key]
    if not sources:
        st.caption("Your added files will appear here.")
        return

    for source in sources:
        name_column, remove_column = st.columns([4, 1], vertical_alignment="center")
        with name_column:
            st.text(source.name)
            st.caption(f"{source.size_bytes / 1024:.0f} KB")
        with remove_column:
            if st.button(
                "✕",
                key=f"{section_key}_remove_{source.file_id}",
                help=f"Remove {source.name} from sources",
            ):
                try:
                    delete_backend_source(
                        get_api_base_url(),
                        st.session_state.backend_session_id,
                        source.file_id,
                    )
                except APIClientError as error:
                    st.error(str(error))
                else:
                    st.session_state[source_state_key] = remove_source_file(
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
        st.markdown("#### Knowledge sources")
        st.caption("Add one file at a time. Remove any source whenever you like.")
        _render_upload_section(
            "Documents",
            "document",
            DOCUMENT_TYPES,
            "document_sources",
            "document_upload_slot",
            "document",
        )
        st.divider()
        _render_upload_section(
            "Images",
            "image",
            IMAGE_TYPES,
            "image_sources",
            "image_upload_slot",
            "image",
        )
        st.divider()
        if st.session_state.backend_error:
            st.error(st.session_state.backend_error)
        else:
            st.markdown(
                '<div class="mediassist-note"><strong>API connected</strong><br>'
                "Documents are indexed for this session. Images are stored only; "
                "OCR and vision analysis are not enabled.</div>",
                unsafe_allow_html=True,
            )


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
            elif exchange.status == "out_of_scope":
                st.caption("This question is outside MediAssist's supported topics.")
            for citation in exchange.citations:
                st.caption(
                    f"[{citation['reference']}] {citation['source']} · "
                    f"chunk {citation['chunk_number']}"
                )


# Submit a question to the session-scoped backend RAG engine.
def _handle_question() -> None:
    question = st.chat_input("Ask about MediAssist healthcare policies or SOPs...")
    if question is None:
        return

    with st.spinner("Searching your session's documents…"):
        try:
            response = ask_backend(
                get_api_base_url(),
                st.session_state.backend_session_id,
                question.strip(),
            )
        except APIClientError as error:
            st.error(str(error))
            return

    exchanges: list[ChatExchange] = st.session_state.chat_exchanges
    st.session_state.chat_exchanges = keep_recent_exchanges(
        [
            *exchanges,
            ChatExchange(
                question=question.strip(),
                answer=response["answer"],
                citations=response["citations"],
                status=response["status"],
            ),
        ]
    )
    st.rerun()


# Assemble the Streamlit interface and connect its actions to FastAPI.
def main() -> None:
    """Run the standalone Streamlit user interface."""
    _configure_page()
    _initialize_session()
    _refresh_sources()
    _render_sidebar()

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
