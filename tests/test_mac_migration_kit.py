import hashlib
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "scripts" / "package_local_workspace.sh"
IMPORT = ROOT / "scripts" / "import_local_workspace.sh"


class MigrationKitTest(unittest.TestCase):
    def make_source(self, root: Path) -> Path:
        source = root / "workspace"
        (source / "data").mkdir(parents=True)
        (source / "review").mkdir()
        (source / "config").mkdir()
        (source / ".git").mkdir()
        (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
        (source / ".env").write_text("ANTHROPIC_API_KEY=secret\n", encoding="utf-8")
        (source / ".env.example").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
        (source / "config" / "paths.local.env").write_text("GL_LOCAL_WORKSPACE=/private\n", encoding="utf-8")
        (source / "config" / "paths.example.env").write_text("GL_LOCAL_WORKSPACE=\n", encoding="utf-8")
        (source / "data" / "cq.json").write_text("{}\n", encoding="utf-8")
        (source / "review" / "vote.json").write_text("{}\n", encoding="utf-8")
        (source / ".git" / "config").write_text("secret\n", encoding="utf-8")
        return source

    def archive_names(self, archive: Path) -> set[str]:
        with tarfile.open(archive, "r:gz") as tf:
            return set(tf.getnames())

    def test_default_package_excludes_secrets_and_clinical_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.make_source(root)
            archive = root / "workspace.migration.tar.gz"
            subprocess.run(
                [str(PACK), "--source", str(source), "--output", str(archive)],
                check=True,
                capture_output=True,
                text=True,
            )
            names = self.archive_names(archive)
            self.assertIn("workspace/app.py", names)
            self.assertIn("workspace/.env.example", names)
            self.assertIn("workspace/config/paths.example.env", names)
            self.assertNotIn("workspace/.env", names)
            self.assertNotIn("workspace/config/paths.local.env", names)
            self.assertNotIn("workspace/data/cq.json", names)
            self.assertNotIn("workspace/review/vote.json", names)
            self.assertNotIn("workspace/.git/config", names)

    def test_include_data_and_verified_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.make_source(root)
            archive = root / "workspace.migration.tar.gz"
            subprocess.run(
                [str(PACK), "--source", str(source), "--output", str(archive), "--include-data"],
                check=True,
                capture_output=True,
                text=True,
            )
            names = self.archive_names(archive)
            self.assertIn("workspace/data/cq.json", names)
            self.assertIn("workspace/review/vote.json", names)
            self.assertNotIn("workspace/.env", names)

            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            destination = root / "imported"
            subprocess.run(
                [str(IMPORT), "--archive", str(archive), "--destination", str(destination), "--sha256", digest],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue((destination / "workspace" / "app.py").is_file())

            repeated = subprocess.run(
                [str(IMPORT), "--archive", str(archive), "--destination", str(destination)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("Refusing to overwrite", repeated.stderr)


if __name__ == "__main__":
    unittest.main()
