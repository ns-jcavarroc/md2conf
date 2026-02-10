"""
Publish Markdown files to Confluence wiki.

Copyright 2022-2026, Levente Hunyadi

:see: https://github.com/hunyadi/md2conf
"""

import copy
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import lxml.etree as ET

ElementType = ET._Element  # pyright: ignore [reportPrivateUsage]

LOGGER = logging.getLogger(__name__)


def _normalize_whitespace(text: str) -> str:
    """Normalizes whitespace in text for comparison."""
    return re.sub(r"\s+", " ", text).strip()


def _get_element_text(elem: ElementType) -> str:
    """Returns all text contained in an element as a concatenated string."""
    return "".join(elem.itertext())


def _get_element_path(elem: ElementType) -> list[str]:
    """
    Returns the structural path to an element.

    Example: ["root", "p[2]", "strong[0]"]
    """
    path: list[str] = []
    current = elem
    while current is not None:
        parent = current.getparent()
        if parent is not None:
            # Find the index of this element among siblings of the same tag
            index = sum(1 for sibling in parent if sibling.tag == current.tag and sibling is not current and list(parent).index(sibling) < list(parent).index(current))
            path.insert(0, f"{current.tag}[{index}]")
        else:
            path.insert(0, str(current.tag))
        current = parent
    return path


def _get_context_text(elem: ElementType, context_chars: int = 50) -> tuple[str, str]:
    """
    Gets text context before and after an element.

    Returns (context_before, context_after) tuple.
    """
    parent = elem.getparent()
    if parent is None:
        return "", ""

    # Get all text in the parent and find our position
    parent_text = _get_element_text(parent)
    elem_text = _get_element_text(elem)

    if not elem_text:
        return "", ""

    # Find the element's text position in parent
    idx = parent_text.find(elem_text)
    if idx < 0:
        return "", ""

    before = parent_text[max(0, idx - context_chars) : idx]
    after_start = idx + len(elem_text)
    after = parent_text[after_start : after_start + context_chars]

    return _normalize_whitespace(before), _normalize_whitespace(after)


@dataclass
class CommentMarker:
    """Represents an inline comment marker extracted from a Confluence page."""

    ref: str  # The ac:ref attribute (comment ID)
    text: str  # The commented text (normalized)
    original_text: str  # The original commented text (not normalized)
    context_before: str  # ~50 chars before the comment
    context_after: str  # ~50 chars after the comment
    element_path: list[str]  # Structural path: ["root", "p[2]", "strong[0]"]
    original_element: ElementType  # The original marker element (for re-insertion)


def extract_comment_markers(name: str, root: ElementType) -> list[CommentMarker]:
    """
    Extracts inline comment markers with rich context for multi-pass matching.

    For each marker, captures:
    - The commented text
    - Surrounding context (text before/after)
    - Structural position in the XML tree

    :param name: The tag name of the comment marker element (e.g., ac:inline-comment-marker).
    :param root: The root element of the XML tree.
    :returns: List of extracted comment markers.
    """
    markers: list[CommentMarker] = []

    for node in root.iterdescendants(name):
        ref = node.get("{http://atlassian.com/content}ref")
        if ref is None:
            continue

        text = _get_element_text(node)
        context_before, context_after = _get_context_text(node)
        element_path = _get_element_path(node)

        # Deep copy the element for later restoration
        original_element = copy.deepcopy(node)

        markers.append(
            CommentMarker(
                ref=ref,
                text=_normalize_whitespace(text),
                original_text=text,
                context_before=context_before,
                context_after=context_after,
                element_path=element_path,
                original_element=original_element,
            )
        )

    return markers


def _find_text_in_element(elem: ElementType, search_text: str) -> tuple[ElementType, int, int] | None:
    """
    Finds a text string within an element tree.

    Returns (text_node_parent, start_offset, end_offset) if found, None otherwise.
    The start_offset and end_offset are character positions within the parent's
    direct text content (either .text or child.tail).
    """
    normalized_search = _normalize_whitespace(search_text)
    if not normalized_search:
        return None

    # Check element's direct text
    if elem.text:
        normalized_elem_text = _normalize_whitespace(elem.text)
        if normalized_search in normalized_elem_text:
            # Find the actual position in the original text
            idx = normalized_elem_text.find(normalized_search)
            return (elem, idx, idx + len(normalized_search))

    # Check children's tail text and recurse
    for child in elem:
        if child.tail:
            normalized_tail = _normalize_whitespace(child.tail)
            if normalized_search in normalized_tail:
                idx = normalized_tail.find(normalized_search)
                # Return child as the reference point, with tail offset
                return (child, idx, idx + len(normalized_search))

        # Recurse into child
        result = _find_text_in_element(child, search_text)
        if result is not None:
            return result

    return None


def _wrap_text_with_marker(
    parent: ElementType,
    text_attr: str,
    start_offset: int,
    end_offset: int,
    marker: CommentMarker,
) -> bool:
    """
    Wraps a portion of text within an element with a comment marker.

    :param parent: The element containing the text (either .text or .tail of a child).
    :param text_attr: Either "text" for parent.text or "tail" for child.tail.
    :param start_offset: Start position in the normalized text.
    :param end_offset: End position in the normalized text.
    :param marker: The comment marker to wrap with.
    :returns: True if successful, False otherwise.
    """
    # Get the original text
    if text_attr == "text":
        original_text = parent.text or ""
    else:
        original_text = parent.tail or ""

    if not original_text:
        return False

    # Normalize and find position mapping
    # We need to map from normalized positions to original positions
    normalized = _normalize_whitespace(original_text)

    # Simple case: find the exact text in the original
    search_text = normalized[start_offset:end_offset]
    original_start = original_text.find(search_text)
    if original_start < 0:
        # Try with whitespace variants
        original_start = original_text.lower().find(search_text.lower())
        if original_start < 0:
            return False
    original_end = original_start + len(search_text)

    # Create the wrapper element
    wrapper = copy.deepcopy(marker.original_element)
    # Clear children - we just want the wrapper
    for child in list(wrapper):
        wrapper.remove(child)
    wrapper.text = original_text[original_start:original_end]
    wrapper.tail = original_text[original_end:]

    if text_attr == "text":
        # Text is in parent.text
        parent.text = original_text[:original_start]
        # Insert wrapper as first child
        parent.insert(0, wrapper)
    else:
        # Text is in a child's tail
        # parent here is actually the child element whose tail we're modifying
        child_elem = parent
        child_parent = child_elem.getparent()
        if child_parent is None:
            return False

        child_elem.tail = original_text[:original_start]
        # Insert wrapper after the child
        child_idx = list(child_parent).index(child_elem)
        child_parent.insert(child_idx + 1, wrapper)

    return True


def _try_exact_match(root: ElementType, marker: CommentMarker) -> bool:
    """
    Pass 1: Try to find an exact match for the commented text.

    :returns: True if the comment was successfully restored.
    """
    if not marker.text:
        return False

    # Search for exact text match in all text nodes
    for elem in root.iter():
        # Check element's direct text
        if elem.text:
            normalized = _normalize_whitespace(elem.text)
            if marker.text in normalized:
                idx = normalized.find(marker.text)
                if _wrap_text_with_marker(elem, "text", idx, idx + len(marker.text), marker):
                    return True

        # Check children's tail text
        for child in elem:
            if child.tail:
                normalized = _normalize_whitespace(child.tail)
                if marker.text in normalized:
                    idx = normalized.find(marker.text)
                    if _wrap_text_with_marker(child, "tail", idx, idx + len(marker.text), marker):
                        return True

    return False


def _try_context_match(root: ElementType, marker: CommentMarker) -> bool:
    """
    Pass 2: Try to find the text using surrounding context.

    :returns: True if the comment was successfully restored.
    """
    if not marker.text:
        return False

    # Build a context string to search for
    search_patterns = []
    if marker.context_before and marker.context_after:
        # Try full context match
        search_patterns.append(marker.context_before + marker.text + marker.context_after)
    if marker.context_before:
        search_patterns.append(marker.context_before + marker.text)
    if marker.context_after:
        search_patterns.append(marker.text + marker.context_after)

    for pattern in search_patterns:
        for elem in root.iter():
            elem_text = _get_element_text(elem)
            normalized_elem = _normalize_whitespace(elem_text)

            if pattern in normalized_elem:
                # Found context match, now locate the exact text position
                pattern_idx = normalized_elem.find(pattern)
                if marker.context_before:
                    text_start = pattern_idx + len(marker.context_before)
                else:
                    text_start = pattern_idx
                text_end = text_start + len(marker.text)

                # Try to wrap at this position
                result = _find_text_in_element(elem, marker.text)
                if result is not None:
                    parent, start, end = result
                    if parent.text and marker.text in _normalize_whitespace(parent.text):
                        if _wrap_text_with_marker(parent, "text", start, end, marker):
                            return True
                    # Check if it's in a tail
                    for child in parent:
                        if child.tail and marker.text in _normalize_whitespace(child.tail):
                            idx = _normalize_whitespace(child.tail).find(marker.text)
                            if _wrap_text_with_marker(child, "tail", idx, idx + len(marker.text), marker):
                                return True

    return False


def _navigate_to_path(root: ElementType, path: list[str]) -> ElementType | None:
    """
    Navigates to an element using a structural path.

    :param root: The root element.
    :param path: The structural path (e.g., ["root", "p[2]", "strong[0]"]).
    :returns: The element at the path, or None if not found.
    """
    if not path:
        return None

    current = root
    # Skip the first path element (root)
    for part in path[1:]:
        # Parse "tag[index]"
        match = re.match(r"^(.+)\[(\d+)\]$", part)
        if not match:
            return None

        tag = match.group(1)
        index = int(match.group(2))

        # Find the child at the specified index
        matching_children = [child for child in current if child.tag == tag]
        if index >= len(matching_children):
            return None

        current = matching_children[index]

    return current


def _find_extended_text(original: str, candidate: str) -> str:
    """
    Find the extended replacement text using SequenceMatcher.

    When text is edited (e.g., "quick brown" -> "fast brown fox"),
    this finds the full replacement text by analyzing the edit operations.

    :param original: The original commented text.
    :param candidate: The candidate text at the same position in the new document.
    :returns: The extended text to wrap with the comment.
    """
    matcher = SequenceMatcher(None, original, candidate)
    opcodes = matcher.get_opcodes()

    # Find the range in candidate that corresponds to the edited text
    # We want to include all text that was inserted/replaced
    min_j = len(candidate)
    max_j = 0

    for tag, i1, i2, j1, j2 in opcodes:
        if tag in ("equal", "replace", "insert"):
            min_j = min(min_j, j1)
            max_j = max(max_j, j2)

    if min_j < max_j:
        return candidate[min_j:max_j]
    return candidate


def _extend_to_word_boundaries(text: str, start: int, end: int) -> tuple[int, int]:
    """
    Extend a text range to include complete words.

    :param text: The full text.
    :param start: Start index of the selection.
    :param end: End index of the selection.
    :returns: Tuple of (extended_start, extended_end).
    """
    # Extend start backwards to word boundary
    while start > 0 and not text[start - 1].isspace():
        start -= 1

    # Extend end forwards to word boundary
    while end < len(text) and not text[end].isspace():
        end += 1

    return start, end


def _try_structural_match(
    root: ElementType,
    marker: CommentMarker,
    threshold: float,
    extend_on_edit: bool = True,
) -> bool:
    """
    Pass 3: Try to match using structural position and text similarity.

    :param threshold: Minimum similarity ratio to accept a match.
    :param extend_on_edit: If True, extend the comment to cover the full replacement text.
    :returns: True if the comment was successfully restored.
    """
    if not marker.text:
        return False

    # Navigate to the same structural position
    target_elem = _navigate_to_path(root, marker.element_path)
    if target_elem is None:
        # Try parent path
        if len(marker.element_path) > 1:
            target_elem = _navigate_to_path(root, marker.element_path[:-1])

    if target_elem is None:
        return False

    # Search within this element for similar text
    elem_text = _get_element_text(target_elem)
    normalized_elem = _normalize_whitespace(elem_text)

    # Use sliding window to find best match
    best_ratio = 0.0
    best_start = 0
    best_end = 0
    search_len = len(marker.text)

    # Try different window sizes to find the best match
    for window_size in [search_len, int(search_len * 1.5), int(search_len * 0.7)]:
        window_size = max(1, min(window_size, len(normalized_elem)))
        for i in range(max(1, len(normalized_elem) - window_size + 1)):
            candidate = normalized_elem[i : i + window_size]
            ratio = SequenceMatcher(None, marker.text, candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i
                best_end = i + window_size

    if best_ratio >= threshold:
        best_text = normalized_elem[best_start:best_end]

        # If extend_on_edit is enabled and this is a fuzzy match (not exact),
        # extend to cover the full replacement text
        if extend_on_edit and best_ratio < 1.0:
            # Extend to word boundaries to capture full replacement
            extended_start, extended_end = _extend_to_word_boundaries(
                normalized_elem, best_start, best_end
            )
            extended_text = normalized_elem[extended_start:extended_end]

            # Use extended text if it's reasonable (not too much longer)
            if len(extended_text) <= len(marker.text) * 2:
                best_text = extended_text
                best_start = extended_start
                best_end = extended_end
                LOGGER.debug(
                    "Extended comment %s to cover full replacement: '%s' -> '%s'",
                    marker.ref,
                    marker.text,
                    best_text,
                )

        # Try to wrap the text
        result = _find_text_in_element(target_elem, best_text)
        if result is not None:
            parent, start, end = result
            if parent.text and best_text in _normalize_whitespace(parent.text):
                if _wrap_text_with_marker(parent, "text", start, end, marker):
                    LOGGER.debug(
                        "Restored comment %s using structural match (similarity: %.2f)",
                        marker.ref,
                        best_ratio,
                    )
                    return True

    return False


def _try_global_similarity_match(
    root: ElementType,
    marker: CommentMarker,
    threshold: float,
    extend_on_edit: bool = True,
) -> bool:
    """
    Pass 4: Try to match using global text similarity search.

    This is a last resort and will log a warning.

    :param threshold: Minimum similarity ratio to accept a match.
    :param extend_on_edit: If True, extend the comment to cover the full replacement text.
    :returns: True if the comment was successfully restored.
    """
    if not marker.text:
        return False

    best_ratio = 0.0
    best_elem: ElementType | None = None
    best_text = ""
    best_start = 0
    best_normalized = ""
    best_is_tail = False

    search_len = len(marker.text)

    for elem in root.iter():
        # Check element's direct text
        if elem.text:
            normalized = _normalize_whitespace(elem.text)
            for window_size in [search_len, int(search_len * 1.5), int(search_len * 0.7)]:
                window_size = max(1, min(window_size, len(normalized)))
                for i in range(max(1, len(normalized) - window_size + 1)):
                    candidate = normalized[i : i + window_size]
                    if len(candidate) < search_len // 2:
                        continue
                    ratio = SequenceMatcher(None, marker.text, candidate).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_elem = elem
                        best_text = candidate
                        best_start = i
                        best_normalized = normalized
                        best_is_tail = False

        # Check children's tail text
        for child in elem:
            if child.tail:
                normalized = _normalize_whitespace(child.tail)
                for window_size in [search_len, int(search_len * 1.5), int(search_len * 0.7)]:
                    window_size = max(1, min(window_size, len(normalized)))
                    for i in range(max(1, len(normalized) - window_size + 1)):
                        candidate = normalized[i : i + window_size]
                        if len(candidate) < search_len // 2:
                            continue
                        ratio = SequenceMatcher(None, marker.text, candidate).ratio()
                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_elem = child
                            best_text = candidate
                            best_start = i
                            best_normalized = normalized
                            best_is_tail = True

    if best_ratio >= threshold and best_elem is not None:
        # If extend_on_edit is enabled and this is a fuzzy match,
        # extend to cover the full replacement text
        if extend_on_edit and best_ratio < 1.0 and best_normalized:
            extended_start, extended_end = _extend_to_word_boundaries(
                best_normalized, best_start, best_start + len(best_text)
            )
            extended_text = best_normalized[extended_start:extended_end]

            # Use extended text if it's reasonable
            if len(extended_text) <= len(marker.text) * 2:
                best_text = extended_text
                best_start = extended_start
                LOGGER.debug(
                    "Extended comment %s to cover full replacement: '%s' -> '%s'",
                    marker.ref,
                    marker.text,
                    best_text,
                )

        # Try to wrap
        if not best_is_tail and best_elem.text and best_text in _normalize_whitespace(best_elem.text):
            idx = _normalize_whitespace(best_elem.text).find(best_text)
            if _wrap_text_with_marker(best_elem, "text", idx, idx + len(best_text), marker):
                LOGGER.warning(
                    "Restored comment %s with low confidence (similarity: %.2f)",
                    marker.ref,
                    best_ratio,
                )
                return True
        elif best_is_tail and best_elem.tail and best_text in _normalize_whitespace(best_elem.tail):
            idx = _normalize_whitespace(best_elem.tail).find(best_text)
            if _wrap_text_with_marker(best_elem, "tail", idx, idx + len(best_text), marker):
                LOGGER.warning(
                    "Restored comment %s with low confidence (similarity: %.2f)",
                    marker.ref,
                    best_ratio,
                )
                return True

    return False


def restore_comment_markers(
    name: str,
    root: ElementType,
    markers: list[CommentMarker],
    similarity_threshold: float = 0.7,
    extend_on_edit: bool = True,
) -> tuple[int, list[CommentMarker]]:
    """
    Attempts to restore comments using multi-pass strategy.

    Pass 1 - Exact Match: Find identical text in the new document
    Pass 2 - Context-Aware Match: Match using surrounding text context
    Pass 3 - Structural + Similarity: Same document position with similar text
    Pass 4 - Global Similarity: Fuzzy match anywhere (last resort, with warning)

    :param name: The tag name of the comment marker element (unused, kept for API consistency).
    :param root: The root element of the new XML tree.
    :param markers: List of comment markers extracted from the original document.
    :param similarity_threshold: Minimum similarity ratio for fuzzy matching (default 0.7).
    :param extend_on_edit: If True, extend comments to cover the full replacement text
        when the original text was modified (default True).
    :returns: Tuple of (restored_count, unrestored_markers).
    """
    restored_count = 0
    unrestored: list[CommentMarker] = []

    for marker in markers:
        restored = False

        # Pass 1: Exact match
        if _try_exact_match(root, marker):
            LOGGER.debug("Restored comment %s using exact match", marker.ref)
            restored = True
        # Pass 2: Context-aware match
        elif _try_context_match(root, marker):
            LOGGER.debug("Restored comment %s using context match", marker.ref)
            restored = True
        # Pass 3: Structural + similarity match
        elif _try_structural_match(root, marker, similarity_threshold, extend_on_edit):
            restored = True
        # Pass 4: Global similarity match (last resort)
        elif _try_global_similarity_match(root, marker, similarity_threshold, extend_on_edit):
            restored = True

        if restored:
            restored_count += 1
        else:
            unrestored.append(marker)

    return restored_count, unrestored
