"""
Snippet & Highlight Generator for ORVIA Search.
Extracts high-density keyword contextual snippets with HTML highlights
and boundary-aware sentence/word clipping.
"""
from __future__ import annotations

import html
import re
from typing import Sequence


class SnippetHighlighter:
    """
    Locates the most relevant passage containing query terms and returns
    an HTML-safe snippet with matching terms highlighted via <mark> tags.
    """

    def __init__(self, default_window_chars: int = 240) -> None:
        self.default_window_chars = default_window_chars

    def generate_snippet(
        self,
        content: str,
        query_terms: Sequence[str],
        window_chars: int | None = None,
        highlight_tag: str = "mark",
        highlight_class: str = "search-highlight",
    ) -> str:
        """
        Generate a contextual snippet from `content` highlighting `query_terms`.
        """
        if not content or not content.strip():
            return ""

        target_window = window_chars or self.default_window_chars
        clean_content = " ".join(content.split())  # collapse redundant whitespace/newlines
        clean_terms = [t.strip().lower() for t in query_terms if t.strip()]

        if not clean_terms:
            # Return initial window
            snippet = clean_content[:target_window].strip()
            if len(clean_content) > target_window:
                snippet += "…"
            return html.escape(snippet)

        # Build regex pattern for all query terms (matching whole words or prefixes)
        # Sort terms by length descending to match longer phrases first
        sorted_terms = sorted(set(clean_terms), key=len, reverse=True)
        escaped_terms = [re.escape(t) for t in sorted_terms]
        pattern_str = r"\b(" + "|".join(escaped_terms) + r")"
        pattern = re.compile(pattern_str, re.IGNORECASE)

        matches = list(pattern.finditer(clean_content))
        if not matches:
            # Fallback to initial segment
            snippet = clean_content[:target_window].strip()
            if len(clean_content) > target_window:
                snippet += "…"
            return html.escape(snippet)

        # Find the best window: sliding window of target_window size containing the most matches
        best_start = 0
        best_end = min(target_window, len(clean_content))
        best_count = 0

        # Evaluate windows starting slightly before each match
        for match in matches:
            m_start = match.start()
            # Try to place the match roughly in the first third of the window
            win_start = max(0, m_start - 60)
            win_end = min(len(clean_content), win_start + target_window)
            if win_end - win_start < target_window and win_start > 0:
                win_start = max(0, win_end - target_window)

            count = sum(1 for m in matches if win_start <= m.start() < win_end)
            if count > best_count:
                best_count = count
                best_start = win_start
                best_end = win_end

        # Adjust boundaries to word boundaries
        if best_start > 0:
            # Find next space
            space_idx = clean_content.find(" ", best_start)
            if space_idx != -1 and space_idx - best_start < 25:
                best_start = space_idx + 1

        if best_end < len(clean_content):
            # Find previous space
            space_idx = clean_content.rfind(" ", best_start, best_end)
            if space_idx != -1 and best_end - space_idx < 25:
                best_end = space_idx

        raw_snippet = clean_content[best_start:best_end].strip()

        # Construct highlighted HTML
        highlighted = self._highlight_text(
            raw_snippet,
            pattern,
            highlight_tag=highlight_tag,
            highlight_class=highlight_class,
        )

        prefix = "… " if best_start > 0 else ""
        suffix = " …" if best_end < len(clean_content) else ""
        return f"{prefix}{highlighted}{suffix}"

    def _highlight_text(
        self,
        text: str,
        pattern: re.Pattern,
        highlight_tag: str,
        highlight_class: str,
    ) -> str:
        """Escape HTML and wrap matched substrings with the highlight tag."""
        pieces: list[str] = []
        last_idx = 0

        for match in pattern.finditer(text):
            m_start, m_end = match.span()
            # Append escaped text before match
            if m_start > last_idx:
                pieces.append(html.escape(text[last_idx:m_start]))

            # Append highlighted match
            matched_text = html.escape(text[m_start:m_end])
            pieces.append(f'<{highlight_tag} class="{highlight_class}">{matched_text}</{highlight_tag}>')
            last_idx = m_end

        # Append trailing text
        if last_idx < len(text):
            pieces.append(html.escape(text[last_idx:]))

        return "".join(pieces)
