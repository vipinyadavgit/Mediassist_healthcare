"""Tests for document text cleanup and the available chunking strategies."""

import unittest

from mediassist_healthcare.text_processing import (
    chunk_by_characters,
    chunk_by_paragraph,
    chunk_by_sentence,
    clean_text,
)


class CleanTextTests(unittest.TestCase):
    """Check that text cleanup standardizes whitespace without losing wording."""

    # Check that repeated whitespace is normalized consistently.
    def test_normalizes_spaces_and_line_breaks(self) -> None:
        """Verify excess spaces and blank lines are reduced consistently."""

        self.assertEqual(
            clean_text("  First   line \n\n\n Second\u00a0line  "),
            "First line\n\nSecond line",
        )

    # Check that whitespace-only input cleans to an empty string.
    def test_empty_text_stays_empty(self) -> None:
        """Verify cleanup handles an empty input."""
        self.assertEqual(clean_text(" \n\t "), "")


class ChunkingTests(unittest.TestCase):
    """Check chunk boundaries, size limits, and invalid settings."""

    # Check that short paragraphs combine only when they fit the size limit.
    def test_paragraph_chunks_combine_short_paragraphs(self) -> None:
        """Verify paragraphs are combined only while they fit the size limit."""

        chunks = chunk_by_paragraph("Alpha\n\nBeta\n\nGamma", max_chars=10)

        self.assertEqual(chunks, ["Alpha Beta", "Gamma"])

    # Check that long paragraphs split at sentence boundaries when possible.
    def test_paragraph_chunks_split_long_paragraph(self) -> None:
        """Verify long paragraphs prefer sentence boundaries while splitting."""

        chunks = chunk_by_paragraph(
            "First sentence. Second sentence.",
            max_chars=18,
        )

        self.assertEqual(chunks, ["First sentence.", "Second sentence."])

    # Check that long unbroken text uses the character-splitting fallback.
    def test_paragraph_chunks_split_long_unbroken_text(self) -> None:
        """Verify long text without sentence boundaries still respects the limit."""

        chunks = chunk_by_paragraph("abcdefgh", max_chars=3)

        self.assertEqual(chunks, ["abc", "def", "gh"])

    # Check that sentence-based chunks keep sentences intact when they fit.
    def test_sentence_chunks_keep_sentences_together_when_possible(self) -> None:
        """Verify sentence boundaries are preferred under the size limit."""

        chunks = chunk_by_sentence("First sentence. Second one.", max_chars=20)

        self.assertEqual(chunks, ["First sentence.", "Second one."])

    # Check that fixed-size chunks repeat the requested overlap.
    def test_character_chunks_include_requested_overlap(self) -> None:
        """Verify adjacent fixed-size chunks repeat the requested characters."""

        chunks = chunk_by_characters("abcdefghij", max_chars=5, overlap=2)

        self.assertEqual(chunks, ["abcde", "defgh", "ghij"])

    # Check that empty input creates no fixed-character chunks.
    def test_empty_text_returns_no_chunks(self) -> None:
        """Verify empty input does not produce an empty chunk."""
        self.assertEqual(chunk_by_characters("", max_chars=5, overlap=0), [])

    # Check that invalid chunk sizes and overlap settings are rejected.
    def test_rejects_invalid_chunk_settings(self) -> None:
        """Verify invalid chunk sizes and overlap fail with clear errors."""

        with self.assertRaisesRegex(ValueError, "max_chars must be greater than zero"):
            chunk_by_paragraph("text", max_chars=0)

        with self.assertRaisesRegex(ValueError, "overlap cannot be negative"):
            chunk_by_characters("text", max_chars=5, overlap=-1)

        with self.assertRaisesRegex(ValueError, "overlap must be smaller than max_chars"):
            chunk_by_characters("text", max_chars=5, overlap=5)


# Allow this test file to run directly as well as through test discovery.
if __name__ == "__main__":
    unittest.main()
