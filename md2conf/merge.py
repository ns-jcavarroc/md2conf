"""
Content merge logic for preserving manual edits while updating from markdown.

Copyright 2022-2026, Levente Hunyadi

:see: https://github.com/hunyadi/md2conf
"""

import logging
from difflib import SequenceMatcher

import lxml.etree as ET

ElementType = ET._Element  # pyright: ignore [reportPrivateUsage]

LOGGER = logging.getLogger(__name__)

# Property key used to store the last generated content
MD2CONF_LAST_GENERATED_KEY = "md2conf-last-generated"


def _elements_equal(elem1: ElementType, elem2: ElementType) -> bool:
    """
    Check if two XML elements are structurally equal (tag, attributes, text).
    """
    if elem1.tag != elem2.tag:
        return False
    if (elem1.text or "").strip() != (elem2.text or "").strip():
        return False
    if (elem1.tail or "").strip() != (elem2.tail or "").strip():
        return False
    if elem1.attrib != elem2.attrib:
        return False
    if len(elem1) != len(elem2):
        return False
    return all(_elements_equal(c1, c2) for c1, c2 in zip(elem1, elem2))


def merge_content(
    previous_generated: ElementType | None,
    current_page: ElementType,
    new_generated: ElementType,
) -> ElementType:
    """
    Performs a 3-way merge of content to preserve manual edits.

    Strategy:
    1. If previous_generated is None or equals current_page:
       No manual edits detected, return new_generated

    2. If previous_generated != current_page:
       Manual edits detected, attempt to merge:
       - Match elements by position (index) and tag
       - For matched elements: if manually edited, keep current; otherwise use new
       - For unmatched elements in current: preserve (manual additions)
       - For unmatched elements in new: add (new content)

    :param previous_generated: The content that was generated from markdown in the last sync (may be None)
    :param current_page: The current page content (may include manual edits)
    :param new_generated: The new content generated from markdown
    :returns: Merged content tree
    """

    # If we don't have previous content, we can't detect manual edits
    # Fall back to full replacement
    if previous_generated is None:
        LOGGER.info("No previous generated content found, using full replacement mode")
        return new_generated

    # Check if current page equals previous generated content
    # If so, no manual edits were made, safe to replace entirely
    from .xml import is_xml_equal
    from .converter import get_volatile_attributes, get_volatile_elements

    if is_xml_equal(
        previous_generated,
        current_page,
        skip_attributes=get_volatile_attributes(),
        skip_elements=get_volatile_elements(),
    ):
        LOGGER.info("No manual edits detected, using full replacement mode")
        return new_generated

    LOGGER.info("Manual edits detected, performing 3-way merge")

    # Build lists of child elements
    prev_children = list(previous_generated)
    curr_children = list(current_page)
    new_children = list(new_generated)

    # Create the merged result by copying the root of new_generated
    import copy
    merged = copy.deepcopy(new_generated)
    merged.clear()  # Remove all children, we'll add them selectively

    # Use index-based matching: elements at the same position with same tag are considered "the same"
    max_len = max(len(prev_children), len(curr_children), len(new_children))

    processed_current_indices = set()

    for i in range(max_len):
        prev_elem = prev_children[i] if i < len(prev_children) else None
        curr_elem = curr_children[i] if i < len(curr_children) else None
        new_elem = new_children[i] if i < len(new_children) else None

        # Case 1: Element exists in all three versions
        if prev_elem is not None and curr_elem is not None and new_elem is not None:
            if prev_elem.tag == curr_elem.tag == new_elem.tag:
                # Same element in all versions
                processed_current_indices.add(i)

                if _elements_equal(prev_elem, curr_elem):
                    # No manual edit, use new version
                    merged.append(copy.deepcopy(new_elem))
                    LOGGER.debug(f"Using new version for element at index {i}: {new_elem.tag}")
                else:
                    # Manual edit detected, preserve current
                    merged.append(copy.deepcopy(curr_elem))
                    LOGGER.debug(f"Preserving manually edited element at index {i}: {curr_elem.tag}")
                continue

        # Case 2: Element only in new (new content added)
        if new_elem is not None and (prev_elem is None or prev_elem.tag != new_elem.tag):
            merged.append(copy.deepcopy(new_elem))
            LOGGER.debug(f"Adding new element at index {i}: {new_elem.tag}")
            # Only mark as processed if they're actually the same element
            if curr_elem is not None and curr_elem.tag == new_elem.tag and prev_elem is not None:
                # prev exists but doesn't match, so current could be processed
                processed_current_indices.add(i)
            # If prev_elem is None, curr_elem at this position is a manual addition, keep it separate

        # Case 3: Element in previous but not in new (removed from markdown)
        if prev_elem is not None and (new_elem is None or new_elem.tag != prev_elem.tag):
            # Check if it still exists in current
            if curr_elem is not None and curr_elem.tag == prev_elem.tag:
                processed_current_indices.add(i)
                # It exists in current, check if manually edited
                if not _elements_equal(prev_elem, curr_elem):
                    # Manually edited, preserve it
                    merged.append(copy.deepcopy(curr_elem))
                    LOGGER.debug(f"Preserving manually edited element at index {i}: {curr_elem.tag}")
                else:
                    # Not edited and removed from new, respect the removal
                    LOGGER.debug(f"Respecting removal of element at index {i}: {prev_elem.tag}")

    # Add any remaining current elements that weren't processed (manual additions at the end)
    for i, curr_elem in enumerate(curr_children):
        if i not in processed_current_indices:
            # Check if this was in previous
            prev_elem_at_i = prev_children[i] if i < len(prev_children) else None
            if prev_elem_at_i is None or prev_elem_at_i.tag != curr_elem.tag:
                # This is a manual addition
                merged.append(copy.deepcopy(curr_elem))
                LOGGER.debug(f"Preserving manually added element at index {i}: {curr_elem.tag}")

    return merged
