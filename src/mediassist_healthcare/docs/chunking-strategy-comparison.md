# MediAssist AI: Text Cleaning and Chunking Strategy

## Purpose

This document describes the Phase 5 text preparation and chunking approaches
used before embedding documents for retrieval. The goal is to make the options
understandable, reproducible, and ready for later evaluation with the project
dataset.

## Text cleaning

The `clean_text` function performs conservative whitespace cleanup:

- converts non-breaking spaces to regular spaces
- reduces repeated spaces and tabs to one space
- removes spaces around line breaks
- reduces three or more consecutive line breaks to a single blank line
- trims whitespace at the beginning and end

It does not intentionally rewrite words, remove punctuation, or infer missing
content. This is important for healthcare material, where small text changes
could change the meaning of a measurement, instruction, or medication name.

## Chunking options

All current strategies use a maximum size measured in **characters**, not
tokens. The default maximum is 1,000 characters. These are prototype settings,
not a claim that one size is optimal for every document or embedding model.

| Strategy | How it works | Strengths | Limitations |
|---|---|---|---|
| Paragraph-first (recommended default) | Keeps paragraphs together when possible. Combines short paragraphs up to the limit. Splits an oversized paragraph at sentence boundaries when possible. | Often keeps a complete thought together and is a simple starting point for policies, SOPs, and reports. | Plain-text extraction may not preserve headings or layout. Sentence detection uses punctuation and may mishandle abbreviations. No overlap is added. |
| Sentence | Groups complete sentences up to the size limit. | Keeps sentence boundaries when combining content. | Can separate sentences that rely on the same heading or surrounding context. |
| Fixed-character | Takes consecutive character ranges up to the size limit, with configurable overlap (100 characters by default). | Simple and predictable baseline; overlap carries a little context across boundaries. | May split a sentence, clinical value, or instruction at an arbitrary point. |

If a sentence or unbroken text unit is itself longer than the limit, the current
implementation falls back to character splitting so every chunk stays within
the configured maximum.

## Recommendation and rationale

Use **paragraph-first chunking as the initial default**. It preserves paragraph
boundaries for ordinary content, while sentence-boundary splitting is a better
fallback for long paragraphs than immediately cutting at an arbitrary
character position. Fixed-character chunking remains available as a baseline
for comparison.

This is a reasoned starting choice, not a measured result. The supplied corpus
and embedding model should be used to compare retrieval quality before
finalizing production settings. In particular:

- extracted text may not retain document headings or table structure
- sentence splitting is punctuation-based and can be affected by abbreviations
- the current size limit is in characters; embedding models have token limits
- overlap is supported only by fixed-character chunking at this stage

Later evaluation should use representative SOPs, policies, and clinical
documents, and compare retrieval relevance, source coverage, chunk count, and
whether important instructions remain understandable in their retrieved
context. After selecting the embedding model, tune chunk sizes with its tokenizer
and document the measured results.

## Reproduce the strategies

From the repository root, run one command per source document:

```powershell
uv run python -m mediassist_healthcare.text_processing "path\to\document.pdf" --strategy paragraph --max-chars 1000
uv run python -m mediassist_healthcare.text_processing "path\to\document.pdf" --strategy sentence --max-chars 1000
uv run python -m mediassist_healthcare.text_processing "path\to\document.pdf" --strategy character --max-chars 1000 --overlap 100
```

Replace the example path with an authorized PDF, DOCX, or TXT file. The command
prints each generated chunk so the boundaries can be inspected. Do not use
real patient information in public repositories, test output, or documentation.

Run the unit tests with:

```powershell
uv run python -m unittest discover -s tests -v
```

## Implementation reference

- Text cleanup and chunking functions: [text_processing.py](../text_processing.py)
- Automated checks: [test_text_processing.py](../../../tests/test_text_processing.py)
