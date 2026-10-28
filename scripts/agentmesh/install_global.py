"""Install a self-contained AgentMesh runtime in the user's OMP directory."""

import datetime
import json
from pathlib import Path
import shutil

import yaml

SOURCE = Path(__file__).resolve().parents[2]


def install(source=SOURCE, home=None):
    home = Path(home or Path.home())
    target = home / ".omp/agentmesh"
    agent = home / ".omp/agent"
    state = source / ".agentmesh"
    shared = target / ".agentmesh"
    if (
        source.resolve() != target.resolve()
        and state.exists()
        and not state.is_symlink()
        and shared.exists()
    ):
        raise RuntimeError(
            "Both source and global state exist; refusing to overwrite either"
        )
    target.mkdir(parents=True, exist_ok=True)
    agent.mkdir(parents=True, exist_ok=True)
    backups = target / "backups"
    backups.mkdir(exist_ok=True, mode=0o700)
    config_path = agent / "config.yml"
    settings = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    settings = settings or {}
    if config_path.exists():
        backup = backups / (
            "config-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".yml"
        )
        shutil.copy2(config_path, backup)
        backup.chmod(0o600)
    if source.resolve() != target.resolve():
        shutil.copytree(
            source / "scripts",
            target / "scripts",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    legacy = target / ".omp/config.yml"
    if legacy.exists():
        legacy.unlink()
    if source.resolve() == target.resolve():
        shared.mkdir(exist_ok=True, mode=0o700)
    elif state.exists() and not state.is_symlink() and not shared.exists():
        shutil.move(str(state), str(shared))
        state.symlink_to(shared, target_is_directory=True)
        old_prefix = str(state / "venv").encode()
        new_prefix = str(shared / "venv").encode()
        for path in [*(shared / "venv/bin").glob("*"), shared / "venv/pyvenv.cfg"]:
            if (
                path.is_file()
                and not path.is_symlink()
                and path.stat().st_size < 1_000_000
            ):
                data = path.read_bytes()
                if b"\0" not in data and old_prefix in data:
                    path.write_bytes(data.replace(old_prefix, new_prefix))
    elif not state.exists():
        shared.mkdir(exist_ok=True, mode=0o700)
        state.symlink_to(shared, target_is_directory=True)
    elif state.is_symlink() and state.resolve() != shared.resolve():
        raise RuntimeError(
            "Existing AgentMesh state points to a different installation"
        )
    elif state.exists() and not state.is_symlink():
        raise RuntimeError(
            "Both source and global state exist; refusing to overwrite either"
        )
    desired = yaml.safe_load(
        (source / "scripts/agentmesh/worker-defaults.yml").read_text()
    )
    for key, value in desired.items():
        if key != "extensions":
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)
            else:
                settings[key] = value
    settings["modelRoleStorage"] = "global"
    config_path.write_text(
        yaml.safe_dump(settings, allow_unicode=True, sort_keys=False)
    )
    config_path.chmod(0o600)
    extensions = agent / "extensions"
    extensions.mkdir(exist_ok=True)
    module = (target / "scripts/agentmesh/extension.ts").as_uri()
    (extensions / "agentmesh.ts").write_text(
        "export { default } from " + json.dumps(module) + ";\n"
    )
    return {
        "installation": str(target),
        "model_name": "Qwen3.6-35B-A3B 4bit",
        "scope": "global",
    }


if __name__ == "__main__":
    print(json.dumps(install(), ensure_ascii=False))
