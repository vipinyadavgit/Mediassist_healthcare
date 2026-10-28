"""Verify Phase 11 frontend session-state helpers."""

from __future__ import annotations

import unittest

from mediassist_healthcare.frontend import (
    ChatExchange,
    SourceFile,
    add_source_file,
    keep_recent_exchanges,
    remove_source_file,
)


class StreamlitFrontendStateTests(unittest.TestCase):
    """Test local chat history and source-list behavior without running Streamlit."""

    def test_chat_history_keeps_latest_five_pairs_in_fifo_order(self) -> None:
        exchanges = [
            ChatExchange(f"Question {number}", f"Answer {number}")
            for number in range(1, 8)
        ]

        recent = keep_recent_exchanges(exchanges)

        self.assertEqual(len(recent), 5)
        self.assertEqual(
            [exchange.question for exchange in recent],
            [
                "Question 3",
                "Question 4",
                "Question 5",
                "Question 6",
                "Question 7",
            ],
        )
        self.assertEqual(
            [exchange.answer for exchange in recent],
            ["Answer 3", "Answer 4", "Answer 5", "Answer 6", "Answer 7"],
        )

    def test_chat_history_keeps_all_exchanges_when_below_limit(self) -> None:
        exchanges = [ChatExchange("Question", "Answer")]

        self.assertEqual(keep_recent_exchanges(exchanges), exchanges)

    def test_add_source_file_appends_name_and_size(self) -> None:
        existing = [SourceFile("existing", "policy.pdf", 1024, "document")]

        updated = add_source_file(
            existing,
            "uploaded",
            "admission.pdf",
            2048,
            "document",
        )

        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[0], existing[0])
        self.assertEqual(updated[1].name, "admission.pdf")
        self.assertEqual(updated[1].size_bytes, 2048)
        self.assertEqual(updated[1].file_id, "uploaded")

    def test_remove_source_file_only_removes_the_selected_file(self) -> None:
        sources = [
            SourceFile("first", "policy.pdf", 1024, "document"),
            SourceFile("second", "admission.pdf", 2048, "document"),
        ]

        remaining = remove_source_file(sources, "first")

        self.assertEqual(remaining, [sources[1]])
        self.assertEqual(len(sources), 2)


if __name__ == "__main__":
    unittest.main()
