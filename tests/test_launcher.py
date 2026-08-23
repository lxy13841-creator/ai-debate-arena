import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.env_path = self.directory / ".env"
        self.example_path = self.directory / ".env.example"
        self.example_path.write_text(
            "MOONSHOT_API_KEY=\nDEEPSEEK_API_KEY=\nOPTION=kept\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(launcher, "ENV_PATH", self.env_path),
            patch.object(launcher, "ENV_EXAMPLE_PATH", self.example_path),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temporary_directory.cleanup()

    def test_write_env_values_preserves_options_and_sets_only_selected_key(self):
        launcher.write_env_values({"MOONSHOT_API_KEY": "secret-value"})

        values = launcher.parse_env_file(self.env_path)
        self.assertEqual(values["MOONSHOT_API_KEY"], "secret-value")
        self.assertEqual(values["DEEPSEEK_API_KEY"], "")
        self.assertEqual(values["OPTION"], "kept")

    def test_has_configured_key_accepts_key_from_env_file(self):
        launcher.write_env_values({"DEEPSEEK_API_KEY": "secret-value"})

        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(launcher.has_configured_key())


if __name__ == "__main__":
    unittest.main()
