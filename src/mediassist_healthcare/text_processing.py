"""Clean extracted healthcare text and create chunks for later embedding.

This module implements Phase 5: whitespace cleanup and three comparable
chunking strategies. It processes one PDF, DOCX, or TXT file per command.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from mediassist_healthcare.ingestion import load_document


# Clean whitespace while preserving the original document wording.
def clean_text(text: str) -> str:
    """Normalize spaces and line breaks without changing the document wording."""

    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Check that the requested chunk size is a positive number.
def _validate_max_chars(max_chars: int) -> None:
    """Reject chunk sizes that cannot produce useful output."""
    if max_chars < 1:
        raise ValueError("max_chars must be greater than zero.")


# Group text units into chunks without exceeding the character limit.
def _chunk_units(units: list[str], max_chars: int) -> list[str]:
    """Group whole text units when possible and split any oversized unit."""

    _validate_max_chars(max_chars)
    chunks: list[str] = []
    current_chunk = ""

    for unit in units:
        unit = unit.strip()
        if not unit:
            continue

        if len(unit) > max_chars:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            chunks.extend(
                unit[start : start + max_chars]
                for start in range(0, len(unit), max_chars)
            )
            continue

        combined_length = len(current_chunk) + len(unit)
        if current_chunk:
            combined_length += 1

        if current_chunk and combined_length > max_chars:
            chunks.append(current_chunk)
            current_chunk = unit
        elif current_chunk:
            current_chunk = f"{current_chunk} {unit}"
        else:
            current_chunk = unit

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# Split a long paragraph at sentence boundaries before using character splits.
def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Split an oversized paragraph at sentence boundaries when possible."""

    if len(paragraph) <= max_chars:
        return [paragraph]

    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    return _chunk_units(sentences, max_chars)


# Create paragraph-first chunks and preserve sentence boundaries when splitting.
def chunk_by_paragraph(text: str, max_chars: int = 1000) -> list[str]:
    """Keep paragraphs together, splitting long ones at sentence boundaries first."""

    cleaned_text = clean_text(text)
    paragraphs = re.split(r"\n{2,}", cleaned_text)
    paragraph_parts = [
        part
        for paragraph in paragraphs
        for part in _split_long_paragraph(paragraph, max_chars)
    ]
    return _chunk_units(paragraph_parts, max_chars)


# Create chunks by grouping complete sentences up to the requested character limit.
def chunk_by_sentence(text: str, max_chars: int = 1000) -> list[str]:
    """Build chunks from sentences while preserving sentence boundaries when possible."""

    cleaned_text = clean_text(text)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned_text)
    return _chunk_units(sentences, max_chars)


# Create fixed-size chunks with a configurable overlap between neighboring chunks.
def chunk_by_characters(
    text: str,
    max_chars: int = 1000,
    overlap: int = 100,
) -> list[str]:
    """Build fixed-length chunks with optional character overlap."""

    _validate_max_chars(max_chars)
    if overlap < 0:
        raise ValueError("overlap cannot be negative.")
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars.")

    cleaned_text = clean_text(text)
    if not cleaned_text:
        return []

    step = max_chars - overlap
    chunks: list[str] = []
    start = 0

    while start < len(cleaned_text):
        end = start + max_chars
        chunks.append(cleaned_text[start:end])
        if end >= len(cleaned_text):
            break
        start += step
    return chunks


# Provide a command-line interface for cleaning and chunking one document.
def main() -> None:
    """Load one document, apply the selected chunking method, and print results."""

    parser = argparse.ArgumentParser(
        description="Clean and chunk one PDF, DOCX, or TXT document."
    )
    parser.add_argument("file", type=Path, help="Path to one supported document")
    parser.add_argument(
        "--strategy",
        choices=("paragraph", "sentence", "character"),
        default="paragraph",
        help="Chunking method to use (default: paragraph)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1000,
        help="Maximum characters in a chunk (default: 1000)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=100,
        help="Character overlap for the character strategy (default: 100)",
    )
    args = parser.parse_args()

    document = load_document(args.file)
    if args.strategy == "paragraph":
        chunks = chunk_by_paragraph(document.text, args.max_chars)
    elif args.strategy == "sentence":
        chunks = chunk_by_sentence(document.text, args.max_chars)
    else:
        chunks = chunk_by_characters(document.text, args.max_chars, args.overlap)

    print(f"Source: {document.source}")
    print(f"Strategy: {args.strategy}")
    print(f"Chunks: {len(chunks)}")
    for number, chunk in enumerate(chunks, start=1):
        print(f"\n--- Chunk {number} ---\n{chunk}")


# Start the command-line chunker only when this file is run directly.
if __name__ == "__main__":
    main()
