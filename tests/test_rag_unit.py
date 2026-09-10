import unittest

from app.rag.ingest import _logical_sections


class RagIngestionTests(unittest.TestCase):
    def test_knowledge_is_split_by_paragraph(self):
        sections = _logical_sections("First fact.\n\nSecond fact.", "darwin_knowledge")
        self.assertEqual(sections, ["First fact.", "Second fact."])

    def test_tasks_are_split_by_nonempty_line(self):
        sections = _logical_sections("One\n\nTwo\n", "tasks")
        self.assertEqual(sections, ["One", "Two"])


if __name__ == "__main__":
    unittest.main()
