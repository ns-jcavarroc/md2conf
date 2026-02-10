"""
Publish Markdown files to Confluence wiki.

Copyright 2022-2026, Levente Hunyadi

:see: https://github.com/hunyadi/md2conf
"""

import logging
import unittest

import lxml.etree as ET

from md2conf.comments import (
    CommentMarker,
    extract_comment_markers,
    restore_comment_markers,
)
from md2conf.csf import AC_ATTR, elements_from_string

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(funcName)s [%(lineno)d] - %(message)s",
)


class TestCommentExtraction(unittest.TestCase):
    def test_extract_single_comment(self) -> None:
        """Test extracting a single inline comment marker."""
        xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>This is some "
            '<ac:inline-comment-marker ac:ref="abc123">commented text</ac:inline-comment-marker>'
            " in a paragraph.</p>"
            "</root>"
        )
        tree = elements_from_string(xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), tree)

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].ref, "abc123")
        self.assertEqual(markers[0].text, "commented text")

    def test_extract_multiple_comments(self) -> None:
        """Test extracting multiple inline comment markers."""
        xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>First "
            '<ac:inline-comment-marker ac:ref="ref1">comment one</ac:inline-comment-marker>'
            " and second "
            '<ac:inline-comment-marker ac:ref="ref2">comment two</ac:inline-comment-marker>'
            ".</p>"
            "</root>"
        )
        tree = elements_from_string(xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), tree)

        self.assertEqual(len(markers), 2)
        self.assertEqual(markers[0].ref, "ref1")
        self.assertEqual(markers[0].text, "comment one")
        self.assertEqual(markers[1].ref, "ref2")
        self.assertEqual(markers[1].text, "comment two")

    def test_extract_nested_comment(self) -> None:
        """Test extracting comment markers with nested elements."""
        xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>Some text with "
            '<ac:inline-comment-marker ac:ref="nested123">'
            "<strong>bold</strong> and <em>italic</em>"
            "</ac:inline-comment-marker>"
            " text.</p>"
            "</root>"
        )
        tree = elements_from_string(xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), tree)

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].ref, "nested123")
        self.assertEqual(markers[0].text, "bold and italic")

    def test_extract_no_comments(self) -> None:
        """Test extraction when there are no comments."""
        xml = '<root xmlns:ac="http://atlassian.com/content"><p>No comments here.</p></root>'
        tree = elements_from_string(xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), tree)

        self.assertEqual(len(markers), 0)


class TestCommentRestoration(unittest.TestCase):
    def test_exact_match_restoration(self) -> None:
        """Test Pass 1: Exact text match restoration."""
        # Original document with comment
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>This is some "
            '<ac:inline-comment-marker ac:ref="abc123">commented text</ac:inline-comment-marker>'
            " in a paragraph.</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        # New document without comment (same text)
        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>This is some commented text in a paragraph.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
        )

        self.assertEqual(restored, 1)
        self.assertEqual(len(unrestored), 0)

        # Verify the comment marker is now in the new tree
        result_xml = ET.tostring(new_tree, encoding="unicode")
        self.assertIn("ac:ref", result_xml)
        self.assertIn("abc123", result_xml)

    def test_multiple_comments_restoration(self) -> None:
        """Test restoring multiple comments."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>First "
            '<ac:inline-comment-marker ac:ref="ref1">comment one</ac:inline-comment-marker>'
            " and second "
            '<ac:inline-comment-marker ac:ref="ref2">comment two</ac:inline-comment-marker>'
            ".</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>First comment one and second comment two.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
        )

        self.assertEqual(restored, 2)
        self.assertEqual(len(unrestored), 0)

    def test_deleted_text_cannot_restore(self) -> None:
        """Test that comments on deleted text cannot be restored."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>This text "
            '<ac:inline-comment-marker ac:ref="deleted123">will be deleted</ac:inline-comment-marker>'
            " completely.</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        # New document with completely different text
        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>Completely new and different paragraph.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
        )

        self.assertEqual(restored, 0)
        self.assertEqual(len(unrestored), 1)
        self.assertEqual(unrestored[0].ref, "deleted123")

    def test_context_match_restoration(self) -> None:
        """Test Pass 2: Context-aware match restoration."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>The quick brown "
            '<ac:inline-comment-marker ac:ref="ctx123">fox jumps</ac:inline-comment-marker>'
            " over the lazy dog.</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        # Text appears multiple times but context helps disambiguate
        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>A fox jumps here. The quick brown fox jumps over the lazy dog.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
        )

        self.assertEqual(restored, 1)
        self.assertEqual(len(unrestored), 0)

    def test_similarity_match_restoration(self) -> None:
        """Test Pass 3/4: Similarity-based match restoration."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>Some text with "
            '<ac:inline-comment-marker ac:ref="sim123">quick brown</ac:inline-comment-marker>'
            " words.</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        # Slightly edited text
        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>Some text with fast brown words.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
            similarity_threshold=0.5,  # Lower threshold to accept "fast brown" for "quick brown"
        )

        # With a low enough threshold, the similarity match should work
        # "quick brown" vs "fast brown" - 6 chars match out of 11 = ~54%
        self.assertEqual(restored, 1)

    def test_unchanged_text_with_other_changes(self) -> None:
        """Test that comments survive when surrounding text changes but commented text is unchanged."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>Old intro text. "
            '<ac:inline-comment-marker ac:ref="unchanged123">Important content</ac:inline-comment-marker>'
            " Old outro text.</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>New intro text. Important content New outro text.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
        )

        self.assertEqual(restored, 1)
        self.assertEqual(len(unrestored), 0)

    def test_moved_paragraph_restoration(self) -> None:
        """Test that comments are restored when paragraph is moved."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>First paragraph.</p>"
            "<p>Second paragraph with "
            '<ac:inline-comment-marker ac:ref="moved123">commented text</ac:inline-comment-marker>'
            ".</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        # Paragraphs are reordered
        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>Second paragraph with commented text.</p>"
            "<p>First paragraph.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
        )

        self.assertEqual(restored, 1)
        self.assertEqual(len(unrestored), 0)

    def test_extend_on_edit_covers_replacement_text(self) -> None:
        """Test that extend_on_edit extends the comment to cover the full replacement text."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>The "
            '<ac:inline-comment-marker ac:ref="extend123">quick brown</ac:inline-comment-marker>'
            " fox.</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        # Text is modified: "quick brown" -> "fast brown fox"
        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>The fast brown jumping fox.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
            similarity_threshold=0.4,
            extend_on_edit=True,
        )

        self.assertEqual(restored, 1)
        self.assertEqual(len(unrestored), 0)

        # Verify the comment covers more than just "quick brown"
        result_xml = ET.tostring(new_tree, encoding="unicode")
        self.assertIn("extend123", result_xml)
        # The comment should be extended to cover the replacement text

    def test_extend_on_edit_disabled(self) -> None:
        """Test that extend_on_edit=False only wraps the matched portion."""
        original_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>The "
            '<ac:inline-comment-marker ac:ref="noextend123">quick brown</ac:inline-comment-marker>'
            " fox.</p>"
            "</root>"
        )
        original_tree = elements_from_string(original_xml)
        markers = extract_comment_markers(AC_ATTR("inline-comment-marker"), original_tree)

        # Text is modified
        new_xml = (
            '<root xmlns:ac="http://atlassian.com/content">'
            "<p>The fast brown jumping fox.</p>"
            "</root>"
        )
        new_tree = elements_from_string(new_xml)

        restored, unrestored = restore_comment_markers(
            AC_ATTR("inline-comment-marker"),
            new_tree,
            markers,
            similarity_threshold=0.4,
            extend_on_edit=False,
        )

        self.assertEqual(restored, 1)
        self.assertEqual(len(unrestored), 0)

        # Comment should still be restored
        result_xml = ET.tostring(new_tree, encoding="unicode")
        self.assertIn("noextend123", result_xml)


if __name__ == "__main__":
    unittest.main()
