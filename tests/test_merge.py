"""
Unit tests for content merge functionality.

Copyright 2022-2026, Levente Hunyadi
"""

import lxml.etree as ET
from md2conf.merge import merge_content

ElementType = ET._Element  # pyright: ignore [reportPrivateUsage]


def _make_element(tag: str, text: str = "", **attrs) -> ElementType:
    """Helper to create XML elements."""
    elem = ET.Element(tag, **attrs)
    elem.text = text
    return elem


def test_merge_no_previous():
    """When no previous content exists, should return new content."""
    current = _make_element("div")
    current.append(_make_element("p", "Current content"))

    new = _make_element("div")
    new.append(_make_element("p", "New content"))

    result = merge_content(None, current, new)

    assert result.tag == "div"
    assert len(result) == 1
    assert result[0].text == "New content"


def test_merge_no_manual_edits():
    """When current equals previous, should return new content."""
    previous = _make_element("div")
    previous.append(_make_element("p", "Generated content"))

    current = _make_element("div")
    current.append(_make_element("p", "Generated content"))

    new = _make_element("div")
    new.append(_make_element("p", "Updated content"))

    result = merge_content(previous, current, new)

    assert len(result) == 1
    assert result[0].text == "Updated content"


def test_merge_manual_edit():
    """When content is manually edited, should preserve the edit."""
    previous = _make_element("div")
    previous.append(_make_element("p", "Generated content"))

    current = _make_element("div")
    current.append(_make_element("p", "Manually edited content"))

    new = _make_element("div")
    new.append(_make_element("p", "Updated generated content"))

    result = merge_content(previous, current, new)

    # Debug output
    print(f"\n  DEBUG test_merge_manual_edit: result has {len(result)} children")
    for i, child in enumerate(result):
        print(f"    [{i}] {child.tag}: '{child.text}'")

    # Should preserve manual edit
    assert len(result) == 1, f"Expected 1 child, got {len(result)}"
    assert result[0].text == "Manually edited content"


def test_merge_manual_addition():
    """When content is manually added, should preserve it."""
    previous = _make_element("div")
    previous.append(_make_element("p", "Generated content"))

    current = _make_element("div")
    current.append(_make_element("p", "Generated content"))
    current.append(_make_element("p", "Manually added"))

    new = _make_element("div")
    new.append(_make_element("p", "Updated generated content"))

    result = merge_content(previous, current, new)

    # Should have both updated content and manual addition
    assert len(result) == 2
    assert result[0].text == "Updated generated content"
    assert result[1].text == "Manually added"


def test_merge_manual_deletion():
    """When content is manually deleted, should respect the deletion."""
    previous = _make_element("div")
    previous.append(_make_element("p", "First paragraph"))
    previous.append(_make_element("p", "Second paragraph"))

    current = _make_element("div")
    current.append(_make_element("p", "First paragraph"))
    # Second paragraph manually deleted

    new = _make_element("div")
    new.append(_make_element("p", "Updated first"))
    new.append(_make_element("p", "Updated second"))

    result = merge_content(previous, current, new)

    # Debug output
    print(f"\n  DEBUG test_merge_manual_deletion: result has {len(result)} children")
    for i, child in enumerate(result):
        print(f"    [{i}] {child.tag}: '{child.text}'")

    # Should only update first, respect deletion of second
    assert len(result) == 1, f"Expected 1 child, got {len(result)}"
    assert result[0].text == "Updated first"


def test_merge_complex_scenario():
    """Test a complex scenario with multiple changes."""
    previous = _make_element("div")
    previous.append(_make_element("h1", "Title"))
    previous.append(_make_element("p", "Intro"))
    previous.append(_make_element("p", "Body"))

    current = _make_element("div")
    current.append(_make_element("h1", "Title"))
    current.append(_make_element("p", "Intro"))
    current.append(_make_element("p", "Manually edited body"))
    current.append(_make_element("p", "Manually added conclusion"))

    new = _make_element("div")
    new.append(_make_element("h1", "Updated Title"))
    new.append(_make_element("p", "Intro"))
    new.append(_make_element("p", "New body content"))
    new.append(_make_element("p", "New section"))

    result = merge_content(previous, current, new)

    # Debug output
    print(f"\n  DEBUG test_merge_complex_scenario: result has {len(result)} children")
    for i, child in enumerate(result):
        print(f"    [{i}] {child.tag}: '{child.text}'")

    # Should have:
    # - Updated title (no manual edit)
    # - Intro (unchanged)
    # - Manually edited body (preserve manual edit)
    # - New section (from new content)
    # - Manually added conclusion (preserve manual addition)
    assert len(result) >= 4, f"Expected at least 4 children, got {len(result)}"
    assert result[0].text == "Updated Title", f"Expected 'Updated Title', got '{result[0].text}'"
    assert result[1].text == "Intro", f"Expected 'Intro', got '{result[1].text}'"
    # Body should preserve manual edit
    assert "Manually edited body" in [elem.text for elem in result], f"Missing 'Manually edited body' in {[elem.text for elem in result]}"
    # Should include manual addition
    assert "Manually added conclusion" in [elem.text for elem in result], f"Missing 'Manually added conclusion' in {[elem.text for elem in result]}"


if __name__ == "__main__":
    # Run tests manually
    print("Running merge tests...")
    try:
        test_merge_no_previous()
        print("PASS: test_merge_no_previous")
    except AssertionError as e:
        print(f"FAIL: test_merge_no_previous - {e}")

    try:
        test_merge_no_manual_edits()
        print("PASS: test_merge_no_manual_edits")
    except AssertionError as e:
        print(f"FAIL: test_merge_no_manual_edits - {e}")

    try:
        test_merge_manual_edit()
        print("PASS: test_merge_manual_edit")
    except AssertionError as e:
        print(f"FAIL: test_merge_manual_edit - {e}")
        import traceback
        traceback.print_exc()

    try:
        test_merge_manual_addition()
        print("PASS: test_merge_manual_addition")
    except AssertionError as e:
        print(f"FAIL: test_merge_manual_addition - {e}")

    try:
        test_merge_manual_deletion()
        print("PASS: test_merge_manual_deletion")
    except AssertionError as e:
        print(f"FAIL: test_merge_manual_deletion - {e}")
        import traceback
        traceback.print_exc()

    try:
        test_merge_complex_scenario()
        print("PASS: test_merge_complex_scenario")
    except AssertionError as e:
        print(f"FAIL: test_merge_complex_scenario - {e}")
        import traceback
        traceback.print_exc()

    print("\nAll tests completed!")
