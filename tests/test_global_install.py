import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

try:
    import yaml
except ImportError:
    yaml = None


@unittest.skipIf(
    yaml is None, "Install the runtime first to test global configuration migration"
)
class GlobalInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.source = Path(self.tmp.name) / "checkout"
        scripts = self.source / "scripts/agentmesh"
        scripts.mkdir(parents=True)
        (scripts / "worker-defaults.yml").write_text(
            json.dumps(
                {
                    "modelRoles": {"default": "anthropic/claude-opus-5-5:high"},
                    "tier": {"anthropic": None, "openai": "priority"},
                    "retry": {"enabled": False},
                }
            )
        )
        (scripts / "extension.ts").write_text("export default function() {}\n")
        (self.source / ".agentmesh").mkdir()
        (self.source / ".agentmesh/weights").write_text("model-data")
        self.agent = self.home / ".omp/agent"
        self.agent.mkdir(parents=True)
        self.original = {
            "startup": {"setupWizard": False},
            "modelRoles": {"advisor": "custom/model"},
            "extensions": ["custom.ts"],
        }
        (self.agent / "config.yml").write_text(json.dumps(self.original))
        path = (
            Path(__file__).resolve().parents[1] / "scripts/agentmesh/install_global.py"
        )
        spec = importlib.util.spec_from_file_location("global_install", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrate_state_and_preserve_unrelated_settings_and_backup(self):
        self.module.install(self.source, self.home)
        target = self.home / ".omp/agentmesh"
        self.assertTrue((self.source / ".agentmesh").is_symlink())
        self.assertEqual((target / ".agentmesh/weights").read_text(), "model-data")
        settings = yaml.safe_load((self.agent / "config.yml").read_text())
        self.assertEqual(settings["modelRoles"]["advisor"], "custom/model")
        self.assertEqual(settings["extensions"], ["custom.ts"])
        self.assertEqual(settings["modelRoleStorage"], "global")
        backup = next((target / "backups").glob("config-*.yml"))
        self.assertEqual(yaml.safe_load(backup.read_text()), self.original)

    def test_reinstall_updates_runtime_without_duplicating_weights_or_extension(self):
        self.module.install(self.source, self.home)
        (self.source / "scripts/agentmesh/extension.ts").write_text("updated")
        self.module.install(self.source, self.home)
        target = self.home / ".omp/agentmesh"
        self.assertEqual(
            (target / "scripts/agentmesh/extension.ts").read_text(), "updated"
        )
        self.assertEqual((target / ".agentmesh/weights").read_text(), "model-data")
        self.assertEqual(
            [p.name for p in (self.agent / "extensions").iterdir()], ["agentmesh.ts"]
        )

    def test_installation_is_independent_of_source_checkout(self):
        self.module.install(self.source, self.home)
        shutil.rmtree(self.source)
        wrapper = (self.agent / "extensions/agentmesh.ts").read_text()
        self.assertNotIn(str(self.source), wrapper)
        target = self.home / ".omp/agentmesh"
        self.assertTrue((target / "scripts/agentmesh/extension.ts").is_file())
        self.assertEqual((target / ".agentmesh/weights").read_text(), "model-data")

    def test_conflicting_state_is_not_overwritten(self):
        shared = self.home / ".omp/agentmesh/.agentmesh"
        shared.mkdir(parents=True)
        (shared / "weights").write_text("existing-global")
        with self.assertRaises(RuntimeError):
            self.module.install(self.source, self.home)
        self.assertEqual((shared / "weights").read_text(), "existing-global")
        self.assertEqual((self.source / ".agentmesh/weights").read_text(), "model-data")

    def test_reinstall_from_global_runtime_itself(self):
        self.module.install(self.source, self.home)
        target = self.home / ".omp/agentmesh"
        self.module.install(target, self.home)
        self.assertEqual((target / ".agentmesh/weights").read_text(), "model-data")

    def test_virtualenv_entrypoints_are_relocated_with_state(self):
        binary = self.source / ".agentmesh/venv/bin/helper"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!" + str(self.source / ".agentmesh/venv/bin/python") + "\n")
        binary.chmod(0o755)
        self.module.install(self.source, self.home)
        target = self.home / ".omp/agentmesh/.agentmesh/venv/bin/helper"
        self.assertEqual(
            target.read_text(), "#!" + str(target.with_name("python")) + "\n"
        )
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
