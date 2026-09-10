import unittest

from app.tools.tasks import get_status


class TaskStatusTests(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(get_status("Ship it - done"), "completed")
        self.assertEqual(get_status("Build it - in-progress"), "in_progress")
        self.assertEqual(get_status("Plan it - pending"), "pending")


if __name__ == "__main__":
    unittest.main()
