import os
import tempfile
import unittest
from unittest.mock import MagicMock

from assistant_connector.tools import memory_tools


def _build_context(memories_dir: str | None = None, user_id: str = "test-user-123"):
    ctx = MagicMock()
    ctx.user_id = user_id
    ctx.memories_dir = memories_dir
    return ctx


class TestListMemoryFiles(unittest.TestCase):
    def test_returns_md_files_in_user_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "about-me.md"), "w").close()
            open(os.path.join(tmp, "health.md"), "w").close()
            open(os.path.join(tmp, "contacts.csv"), "w").close()  # non-.md, excluded

            result = memory_tools.list_memory_files({}, _build_context(memories_dir=tmp))

        self.assertEqual(result["count"], 2)
        self.assertIn("about-me.md", result["files"])
        self.assertIn("health.md", result["files"])

    def test_excludes_readme_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "readme.md"), "w").close()
            open(os.path.join(tmp, "README.md"), "w").close()
            open(os.path.join(tmp, "about-me.md"), "w").close()

            result = memory_tools.list_memory_files({}, _build_context(memories_dir=tmp))

        self.assertEqual(result["count"], 1)
        self.assertNotIn("readme.md", result["files"])
        self.assertNotIn("README.md", result["files"])

    def test_returns_empty_when_dir_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = os.path.join(tmp, "no-such-dir")
            result = memory_tools.list_memory_files({}, _build_context(memories_dir=nonexistent))

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["files"], [])

    def test_raises_when_memories_dir_not_configured(self):
        with self.assertRaises(ValueError):
            memory_tools.list_memory_files({}, _build_context(memories_dir=None))


class TestReadMemoryFile(unittest.TestCase):
    def test_reads_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "about-me.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# About me\n\nI am a test user.")

            result = memory_tools.read_memory_file({"file_name": "about-me.md"}, _build_context(memories_dir=tmp))

        self.assertEqual(result["file_name"], "about-me.md")
        self.assertIn("test user", result["content"])
        self.assertGreater(result["chars"], 0)

    def test_returns_error_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = memory_tools.read_memory_file({"file_name": "missing.md"}, _build_context(memories_dir=tmp))

        self.assertEqual(result["error"], "file_not_found")

    def test_raises_for_invalid_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                memory_tools.read_memory_file({"file_name": "../../etc/passwd"}, _build_context(memories_dir=tmp))

    def test_raises_for_non_md_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                memory_tools.read_memory_file({"file_name": "data.csv"}, _build_context(memories_dir=tmp))

    def test_raises_for_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                memory_tools.read_memory_file({"file_name": "readme.md"}, _build_context(memories_dir=tmp))

    def test_raises_when_memories_dir_not_configured(self):
        with self.assertRaises(ValueError):
            memory_tools.read_memory_file({"file_name": "about-me.md"}, _build_context(memories_dir=None))


class TestEditMemoryFile(unittest.TestCase):
    def test_replace_creates_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = memory_tools.edit_memory_file(
                {"file_name": "health.md", "content": "# Health\n\nGood shape.", "mode": "replace"},
                _build_context(memories_dir=tmp),
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "replaced")
            self.assertEqual(result["file_name"], "health.md")

            with open(os.path.join(tmp, "health.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "# Health\n\nGood shape.")

    def test_replace_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "work.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("old content")

            memory_tools.edit_memory_file(
                {"file_name": "work.md", "content": "new content", "mode": "replace"},
                _build_context(memories_dir=tmp),
            )

            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "new content")

    def test_append_adds_to_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("first line")

            memory_tools.edit_memory_file(
                {"file_name": "notes.md", "content": "second line", "mode": "append"},
                _build_context(memories_dir=tmp),
            )

            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("first line", content)
            self.assertIn("second line", content)

    def test_append_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = memory_tools.edit_memory_file(
                {"file_name": "new-file.md", "content": "initial content", "mode": "append"},
                _build_context(memories_dir=tmp),
            )

            self.assertEqual(result["action"], "appended")
            with open(os.path.join(tmp, "new-file.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "initial content")

    def test_default_mode_is_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = memory_tools.edit_memory_file(
                {"file_name": "notes.md", "content": "content without mode"},
                _build_context(memories_dir=tmp),
            )

        self.assertEqual(result["action"], "appended")

    def test_creates_missing_directory(self):
        with tempfile.TemporaryDirectory() as base:
            user_dir = os.path.join(base, "new-user-dir")

            result = memory_tools.edit_memory_file(
                {"file_name": "about-me.md", "content": "hello", "mode": "replace"},
                _build_context(memories_dir=user_dir),
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(os.path.isfile(os.path.join(user_dir, "about-me.md")))

    def test_raises_for_invalid_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                memory_tools.edit_memory_file(
                    {"file_name": "notes.md", "content": "x", "mode": "overwrite"},
                    _build_context(memories_dir=tmp),
                )

    def test_raises_for_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                memory_tools.edit_memory_file(
                    {"file_name": "../escape.md", "content": "bad"},
                    _build_context(memories_dir=tmp),
                )

    def test_raises_for_special_characters_in_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                memory_tools.edit_memory_file(
                    {"file_name": "bad file!.md", "content": "x"},
                    _build_context(memories_dir=tmp),
                )

    def test_raises_for_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                memory_tools.edit_memory_file(
                    {"file_name": "README.md", "content": "x"},
                    _build_context(memories_dir=tmp),
                )

    def test_raises_when_memories_dir_not_configured(self):
        with self.assertRaises(ValueError):
            memory_tools.edit_memory_file(
                {"file_name": "notes.md", "content": "x"},
                _build_context(memories_dir=None),
            )

    def test_raises_for_symlink_file(self):
        """Symlinks inside the memories dir must be rejected to prevent arbitrary file access."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            target = os.path.join(outside, "secret.md")
            with open(target, "w") as f:
                f.write("secret")
            link = os.path.join(tmp, "symlinked.md")
            os.symlink(target, link)
            with self.assertRaises(ValueError):
                memory_tools.read_memory_file({"file_name": "symlinked.md"}, _build_context(memories_dir=tmp))
            with self.assertRaises(ValueError):
                memory_tools.edit_memory_file(
                    {"file_name": "symlinked.md", "content": "x"}, _build_context(memories_dir=tmp)
                )


if __name__ == "__main__":
    unittest.main()
