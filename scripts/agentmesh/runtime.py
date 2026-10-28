#!/usr/bin/env python3
"""AgentMesh durable DAG executor. Credentials remain in OMP / Codex CLI."""

from __future__ import annotations
import argparse, concurrent.futures, contextlib, fcntl, hashlib, json, os, re, shutil, signal, subprocess, sys, threading, time, urllib.request, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".agentmesh"
PROFILES = json.loads((ROOT / "scripts/agentmesh/profiles.json").read_text())
LOCAL_MODEL = STATE / "models/Qwen3.6-35B-A3B-4bit"
PORT = 18541
ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
CANCEL = threading.Event()
CHILDREN: set[subprocess.Popen] = set()
MUTEX = threading.Lock()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.chmod(0o600)
    temp.replace(path)


def inside(workspace, value, allow_root=False):
    p = (workspace / value).resolve()
    if (
        not p.is_relative_to(workspace)
        or (p == workspace and not allow_root)
        or ".git" in p.relative_to(workspace).parts
    ):
        raise ValueError(f"Path outside allowed workspace: {value}")
    return p


def validate(plan):
    tasks = plan.get("tasks", [])
    if not 1 <= len(tasks) <= 16:
        raise ValueError("Plan requires 1..16 tasks")
    workspace = Path(plan.get("workspace") or ROOT).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("Workspace not found")
    for key, default, maximum in [
        ("task_timeout", 600, 1200),
        ("run_timeout", 1800, 7200),
    ]:
        value = plan.get(key, default)
        if not isinstance(value, (int, float)) or not 0 < value <= maximum:
            raise ValueError(f"Invalid {key}")
    ids = set()
    for t in tasks:
        ident = t.get("id", "")
        if not ID.fullmatch(ident) or ident in ids:
            raise ValueError("Invalid or duplicate task id")
        ids.add(ident)
        if t.get("profile") not in PROFILES or t["profile"] == "coordinator":
            raise ValueError("Unknown worker profile")
        if not t.get("instruction", "").strip() or not t.get("acceptance"):
            raise ValueError("Instruction and acceptance required")
        for field in ("context_files", "context_images", "read_paths", "write_paths"):
            t[field] = [
                str(
                    inside(
                        workspace, path, allow_root=field == "read_paths"
                    ).relative_to(workspace)
                )
                for path in t.get(field, [])
            ]
        if t.get("write_paths") and not t.get("checks"):
            raise ValueError("Writing tasks require executable checks")
        if t["profile"] == "local" and t.get("context_images"):
            raise ValueError("Visual checks require a vision-capable cloud worker")
        if t["profile"] == "local" and not t.get("scope_confirmed"):
            raise ValueError("Local scope must be explicitly confirmed")
        for check in t.get("checks", []):
            if (
                not isinstance(check, list)
                or not check
                or not all(isinstance(x, str) for x in check)
            ):
                raise ValueError("Checks must be argv arrays")
        for d in t.get("depends_on", []):
            if d == ident:
                raise ValueError("Self dependency")
    graph = {t["id"]: set(t.get("depends_on", [])) for t in tasks}
    if any(not ds <= ids for ds in graph.values()):
        raise ValueError("Unknown dependency")
    done = set()
    while len(done) < len(ids):
        ready = {i for i, deps in graph.items() if i not in done and deps <= done}
        if not ready:
            raise ValueError("Cyclic dependencies")
        done.update(ready)
    plan["workspace"] = str(workspace)
    return plan


def snapshot(workspace):
    result = {}
    for base, dirs, files in os.walk(workspace):
        dirs[:] = [
            d
            for d in dirs
            if d
            not in {
                ".git",
                ".agentmesh",
                "node_modules",
                ".venv",
                "venv",
                "__pycache__",
                ".cache",
                "dist",
                "build",
            }
        ]
        links = [d for d in dirs if (Path(base) / d).is_symlink()]
        dirs[:] = [d for d in dirs if d not in links]
        for name in files + links:
            p = Path(base) / name
            key = str(p.relative_to(workspace))
            if p.is_symlink():
                result[key] = "symlink:" + os.readlink(p)
                continue
            if not p.is_file():
                continue
            stat = p.stat()
            if stat.st_size > 16 * 1024 * 1024:
                result[key] = (
                    f"large:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
                )
            else:
                result[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def allowed(path, scope):
    return any(
        s == "." or path == s.rstrip("/") or path.startswith(s.rstrip("/") + "/")
        for s in scope
    )


def fingerprint(workspace, task, current=None):
    scope = (
        task.get("context_files", [])
        + task.get("context_images", [])
        + task.get("read_paths", [])
        + task.get("write_paths", [])
    )
    current = snapshot(workspace) if current is None else current
    return {path: value for path, value in current.items() if allowed(path, scope)}


def execute(cmd, cwd, log, timeout=600, env=None):
    with log.open("w") as out:
        input_stream = (
            open(env["AGENTMESH_STDIN"], "r")
            if env and env.get("AGENTMESH_STDIN")
            else subprocess.DEVNULL
        )
        p = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/agentmesh/process_guard.py"), *cmd],
            cwd=cwd,
            env=env,
            stdin=input_stream,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if input_stream != subprocess.DEVNULL:
            input_stream.close()
        with MUTEX:
            CHILDREN.add(p)
        deadline = time.monotonic() + timeout
        try:
            while p.poll() is None:
                if CANCEL.is_set() or time.monotonic() > deadline:
                    os.killpg(p.pid, signal.SIGTERM)
                    try:
                        p.wait(5)
                    except subprocess.TimeoutExpired:
                        os.killpg(p.pid, signal.SIGKILL)
                        p.wait()
                    return 130 if CANCEL.is_set() else 124
                time.sleep(0.1)
            return p.returncode
        finally:
            with MUTEX:
                CHILDREN.discard(p)


@contextlib.contextmanager
def local_server(timeout=180):
    STATE.mkdir(exist_ok=True, mode=0o700)
    with (STATE / "local.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (
            not (LOCAL_MODEL / "model.safetensors.index.json").exists()
            or len(list(LOCAL_MODEL.glob("model-*.safetensors"))) != 4
        ):
            raise RuntimeError("Local model download incomplete; run scripts/setup.sh")
        verified = STATE / "download/verified.json"
        if not verified.exists():
            raise RuntimeError(
                "Model integrity verification missing; run scripts/setup.sh"
            )
        manifest = json.loads(verified.read_text())
        if not manifest.get("sha256_verified") or any(
            not (LOCAL_MODEL / name).exists()
            or (LOCAL_MODEL / name).stat().st_size != meta["size"]
            for name, meta in manifest.get("files", {}).items()
        ):
            raise RuntimeError("Model files changed; run scripts/setup.sh")
        python = STATE / "venv/bin/python"
        if not python.exists():
            raise RuntimeError("Local runtime missing; run scripts/setup.sh")
        import socket

        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", PORT)) == 0:
                raise RuntimeError(
                    "Local model port is occupied; refusing to reuse an unknown server"
                )
            log = (STATE / "local-server.log").open("a")
        p = subprocess.Popen(
            [
                str(python),
                str(ROOT / "scripts/agentmesh/serve_local.py"),
                "--model",
                str(LOCAL_MODEL),
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
                "--allowed-origins",
                "http://127.0.0.1:" + str(PORT),
                "--decode-concurrency",
                "1",
                "--prompt-concurrency",
                "1",
                "--prompt-cache-size",
                "1",
                "--prompt-cache-bytes",
                "536870912",
                "--prefill-step-size",
                "256",
                "--max-tokens",
                "4096",
                "--chat-template-args",
                '{"enable_thinking":true}',
                "--log-level",
                "WARNING",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + min(180, timeout)
            while time.monotonic() < deadline:
                if p.poll() is not None:
                    raise RuntimeError(
                        "MLX startup failed; see .agentmesh/local-server.log"
                    )
                if CANCEL.is_set():
                    raise RuntimeError("Cancelled")
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{PORT}/v1/models", timeout=2
                    ):
                        break
                except Exception:
                    time.sleep(0.4)
            else:
                raise RuntimeError("MLX startup timed out")
            yield
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
            log.close()


def parse_worker(log):
    final = ""
    error = None
    model = None
    usage = {}
    for line in log.read_text(errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        m = obj.get("message", {})
        if obj.get("type") == "message_end" and m.get("role") == "assistant":
            model = m.get("model")
            usage = m.get("usage", {})
            if m.get("stopReason") in ("error", "aborted"):
                error = m.get("errorMessage", m["stopReason"])
            text = "\n".join(
                b.get("text", "")
                for b in m.get("content", [])
                if b.get("type") == "text"
            )
            if text:
                final = text
    return final, error, model, usage


def parse_codex(log, requested_model):
    final = ""
    error = None
    usage = {}
    for line in log.read_text(errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if (
            obj.get("type") == "item.completed"
            and obj.get("item", {}).get("type") == "agent_message"
        ):
            final = obj["item"].get("text", "")
        if obj.get("type") == "turn.completed":
            usage = obj.get("usage", {})
        if obj.get("type") in ("turn.failed", "error"):
            error = (
                obj.get("error", {}).get("message")
                if isinstance(obj.get("error"), dict)
                else obj.get("message") or str(obj.get("error"))
            )
    return final, error, requested_model, usage


def worker(task, plan, run_dir, results, executor=None):
    deadline = time.monotonic() + plan.get("task_timeout", 600)
    workspace = Path(plan["workspace"])
    profile = PROFILES[task["profile"]]
    attempt_dir = run_dir / f"{task['id']}-{uuid.uuid4().hex[:6]}"
    attempt_dir.mkdir(mode=0o700)
    payload = {
        "task": task,
        "common_constraints": plan.get("common_context", ""),
        "predecessors": {d: results[d] for d in task.get("depends_on", [])},
    }
    payload["context_files"] = {}
    for name in task.get("context_files", []):
        p = inside(workspace, name)
        if p.stat().st_size > 200_000:
            raise ValueError("Context file too large; narrow the requested input")
        payload["context_files"][name] = p.read_text()
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if task["profile"] == "local" and len(serialized.encode("utf-8")) > 24000:
        raise ValueError(
            "Local context exceeds budget; narrow this part before reassignment"
        )
    request = attempt_dir / "request.md"
    request.write_text(serialized)
    request.chmod(0o600)
    worker_config = attempt_dir / "worker-config.yml"
    selector = profile["model"] + ":" + profile["thinking"]
    atomic(
        worker_config,
        {
            "modelRoles": {
                role: selector
                for role in (
                    "default",
                    "plan",
                    "task",
                    "smol",
                    "slow",
                    "tiny",
                    "memory",
                    "advisor",
                    "vision",
                )
            },
            "retry": {"enabled": False, "waitForUsageReset": False},
        },
    )
    env = os.environ.copy()
    env["AGENTMESH_WORKER"] = "1"
    env["AGENTMESH_WORKER_SPEC"] = str(request)
    tools = "read,grep,glob"
    if task.get("write_paths"):
        tools += ",mesh_write" if task["profile"] == "local" else ",edit,write"
    if task["profile"] != "local" and task.get("write_paths"):
        tools += ",bash"
    cmd = [
        shutil.which("omp") or "omp",
        "--cwd",
        str(workspace),
        "--config",
        str(ROOT / "scripts/agentmesh/worker-defaults.yml"),
        "--config",
        str(worker_config),
        "--no-extensions",
        "--extension",
        str(ROOT / "scripts/agentmesh/extension.ts"),
        "--no-skills",
        "--no-rules",
        "--no-session",
        "--no-title",
        "--no-lsp",
        "--no-pty",
        "--tools",
        tools,
        "--model",
        profile["model"],
        "--thinking",
        profile["thinking"],
        "--approval-mode",
        "yolo",
        "--mode",
        "json",
        "--max-time",
        str(plan.get("task_timeout", 600)),
        "-p",
        "@" + str(request),
    ]
    if profile.get("backend") == "codex-cli":
        native = attempt_dir / "native-request.md"
        native.write_text(
            (ROOT / "scripts/agentmesh/worker.md").read_text()
            + "\nYou are a cloud Codex implementation worker. Use native Codex tools directly. mesh_write is Qwen-only and is not required or available to you. Coordinator-only mesh_run rules do not apply.\n"
            + request.read_text()
        )
        env["AGENTMESH_STDIN"] = str(native)
        cmd = [
            shutil.which("codex") or "codex",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--disable",
            "multi_agent",
            "--disable",
            "multi_agent_v2",
            "--model",
            profile["model"].split("/", 1)[1],
            "-c",
            "model_reasoning_effort=" + json.dumps(profile["thinking"]),
            "-c",
            'service_tier="fast"',
            "-",
        ]
        with (STATE / "request-audit.jsonl").open("a") as audit:
            audit.write(
                json.dumps(
                    {
                        "time": time.time(),
                        "worker": True,
                        "provider": "codex-cli",
                        "model": profile["model"].split("/", 1)[1],
                        "model_source": "explicit CLI argument",
                        "requested_service_tier": "fast",
                        "effort": profile["thinking"],
                    }
                )
                + "\n"
            )
    for image in task.get("context_images", []):
        path = inside(workspace, image)
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Invalid image attachment")
        if profile.get("backend") == "codex-cli":
            cmd[-1:-1] = ["--image", str(path)]
        else:
            cmd.append("@" + str(path))
    start = time.time()
    before = snapshot(workspace)
    with (
        local_server(max(0, deadline - time.monotonic()))
        if task["profile"] == "local" and executor is None
        else contextlib.nullcontext()
    ):
        rc = (executor or execute)(
            cmd,
            workspace,
            attempt_dir / "worker.jsonl",
            max(0, deadline - time.monotonic()),
            env,
        )
    final, error, model, usage = (
        parse_codex(attempt_dir / "worker.jsonl", profile["model"].split("/", 1)[1])
        if profile.get("backend") == "codex-cli"
        else parse_worker(attempt_dir / "worker.jsonl")
    )
    after = snapshot(workspace)
    changed = sorted(
        p for p in before.keys() | after.keys() if before.get(p) != after.get(p)
    )
    violations = [p for p in changed if not allowed(p, task.get("write_paths", []))]
    checks = []
    if rc == 0 and not error and final and not violations:
        for i, argv in enumerate(task.get("checks", [])):
            code = execute(
                argv,
                workspace,
                attempt_dir / f"check-{i}.log",
                max(0, min(deadline - time.monotonic(), 300)),
            )
            checks.append(
                {
                    "argv": argv,
                    "exit_code": code,
                    "log": str((attempt_dir / f"check-{i}.log").relative_to(STATE)),
                }
            )
            if code:
                break
    after_checks = snapshot(workspace)
    changed = sorted(
        p
        for p in before.keys() | after_checks.keys()
        if before.get(p) != after_checks.get(p)
    )
    violations = [p for p in changed if not allowed(p, task.get("write_paths", []))]
    expected = profile["model"].split("/", 1)[1]
    model_ok = (
        model == expected or task["profile"] == "local" and model == str(LOCAL_MODEL)
    )
    ok = (
        rc == 0
        and not error
        and bool(final)
        and not violations
        and model_ok
        and all(c["exit_code"] == 0 for c in checks)
    )
    if task.get("write_paths") and len(checks) != len(task.get("checks", [])):
        ok = False
    result = {
        "status": "passed" if ok else "failed",
        "profile": task["profile"],
        "model": model,
        "thinking": profile["thinking"],
        "result": final,
        "error": error or (f"Worker exit {rc}" if rc else None),
        "changed_files": changed,
        "scope_violations": violations,
        "checks": checks,
        "usage": usage,
        "duration_seconds": round(time.time() - start, 2),
        "artifacts": str(attempt_dir.relative_to(STATE)),
    }
    result["model_source"] = (
        "explicit CLI argument; CLI response does not expose model identity"
        if profile.get("backend") == "codex-cli"
        else "OMP response metadata"
    )
    result["file_fingerprint"] = fingerprint(workspace, task, after_checks)
    if not model_ok:
        result["model_error"] = "Worker model did not match configured profile"
    atomic(attempt_dir / "result.json", result)
    return result


def run(plan, run_id=None, executor=None):
    validate(plan)
    STATE.mkdir(exist_ok=True, mode=0o700)
    # One mutation-owning workflow per project; independent read-only tasks inside it still run concurrently.
    with (STATE / "workflow.lock").open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if CANCEL.is_set():
                    raise RuntimeError("Cancelled while waiting for workspace lock")
                time.sleep(0.2)
        if run_id and not ID.fullmatch(run_id):
            raise ValueError("Invalid run id")
        run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        run_dir = STATE / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        state_path = run_dir / "state.json"
        state = (
            json.loads(state_path.read_text())
            if state_path.exists()
            else {
                "run_id": run_id,
                "results": {},
                "attempts": {},
                "created": time.time(),
            }
        )
        state["owner_pid"] = os.getpid()
        state["status"] = "running"
        old = (
            json.loads((run_dir / "plan.json").read_text())
            if (run_dir / "plan.json").exists()
            else None
        )
        if old and old["workspace"] != plan["workspace"]:
            raise ValueError("Cannot change workspace on resume")
        if old:
            old_tasks = {t["id"]: t for t in old["tasks"]}
            dirty = {t["id"] for t in plan["tasks"] if old_tasks.get(t["id"]) != t}
            current = snapshot(Path(plan["workspace"]))
            dirty.update(
                t["id"]
                for t in plan["tasks"]
                if "file_fingerprint" in state["results"].get(t["id"], {})
                and state["results"][t["id"]]["file_fingerprint"]
                != fingerprint(Path(plan["workspace"]), t, current)
            )
            if old.get("common_context", "") != plan.get("common_context", ""):
                dirty.update(t["id"] for t in plan["tasks"])
            state["results"] = {
                key: value
                for key, value in state["results"].items()
                if key in {t["id"] for t in plan["tasks"]}
            }
            while True:
                more = {
                    t["id"]
                    for t in plan["tasks"]
                    if set(t.get("depends_on", [])) & dirty
                }
                if more <= dirty:
                    break
                dirty.update(more)
            for key in dirty:
                state["results"].pop(key, None)
        atomic(run_dir / "plan.json", plan)
        pending = {
            t["id"]: t
            for t in plan["tasks"]
            if state["results"].get(t["id"], {}).get("status") != "passed"
        }
        state["run_timeout"] = min(
            state.get("run_timeout", plan.get("run_timeout", 1800)),
            plan.get("run_timeout", 1800),
        )
        deadline = state["created"] + state["run_timeout"]

        def persist():
            atomic(state_path, state)

        persist()
        while pending and not CANCEL.is_set():
            ready = [
                t
                for t in pending.values()
                if all(
                    state["results"].get(d, {}).get("status") == "passed"
                    for d in t.get("depends_on", [])
                )
            ]
            ready = [
                t
                for t in ready
                if state["attempts"].get(t["id"], 0) < 3 and time.time() < deadline
            ]
            if not ready:
                break
            # Concurrent read-only tasks; any writing task obtains the whole workspace lane.
            readers = [t for t in ready if not t.get("write_paths")]
            batch = readers[:3] if readers else ready[:1]
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = {}
                for t in batch:
                    ident = t["id"]
                    state["attempts"][ident] = state["attempts"].get(ident, 0) + 1
                    state["results"][ident] = {"status": "running"}
                    persist()
                    bounded_plan = {
                        **plan,
                        "task_timeout": min(
                            plan.get("task_timeout", 600),
                            max(0, deadline - time.time()),
                        ),
                    }
                    futures[
                        pool.submit(
                            worker,
                            t,
                            bounded_plan,
                            run_dir,
                            dict(state["results"]),
                            executor,
                        )
                    ] = ident
                for f in concurrent.futures.as_completed(futures):
                    ident = futures[f]
                    try:
                        result = f.result()
                    except Exception as e:
                        result = {"status": "failed", "error": str(e)}
                    state["results"][ident] = result
                    pending.pop(ident)
                    persist()
                    print(
                        json.dumps(
                            {
                                "task": ident,
                                "status": result["status"],
                                "run_id": run_id,
                            }
                        ),
                        flush=True,
                    )
        for ident in pending:
            if state["results"].get(ident, {}).get("status") == "failed":
                state["results"][ident]["blocked_reason"] = (
                    "Retry limit reached or run budget exhausted"
                )
            else:
                state["results"][ident] = {
                    "status": "cancelled" if CANCEL.is_set() else "blocked",
                    "error": "Dependency failed, retry limit reached, or time budget exhausted",
                }
        state["status"] = (
            "passed"
            if all(
                state["results"].get(t["id"], {}).get("status") == "passed"
                for t in plan["tasks"]
            )
            else "incomplete"
        )
        persist()
        return state


def cancel(signum, frame):
    CANCEL.set()
    with MUTEX:
        for p in list(CHILDREN):
            if p.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGTERM)


def status(run_id=None, workspace=None):
    paths = sorted((STATE / "runs").glob("*/state.json"), reverse=True)
    if run_id:
        if not ID.fullmatch(run_id):
            raise ValueError("Invalid run id")
        paths = [STATE / "runs" / run_id / "state.json"]
    elif workspace:
        target = Path(workspace).resolve()
        paths = [
            p
            for p in paths
            if Path(
                json.loads((p.parent / "plan.json").read_text())["workspace"]
            ).resolve()
            == target
        ]
    result = json.loads(paths[0].read_text()) if paths else {"status": "no_runs"}
    if result.get("status") == "running":
        try:
            os.kill(result.get("owner_pid", 0), 0)
        except ProcessLookupError:
            result["status"] = "interrupted"
            for item in result["results"].values():
                if item.get("status") == "running":
                    item["status"] = "interrupted"
    return result


def main():
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    parent = os.getppid()

    def watch_parent():
        while not CANCEL.wait(1):
            if os.getppid() != parent:
                cancel(None, None)
                return

    threading.Thread(target=watch_parent, daemon=True).start()
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "status", "doctor"])
    parser.add_argument("--request")
    parser.add_argument("--run-id")
    parser.add_argument("--workspace")
    args = parser.parse_args()
    if args.action == "run":
        request = json.loads(Path(args.request).read_text())
        result = run(request["plan"], request.get("run_id"))
    elif args.action == "status":
        result = status(args.run_id, args.workspace)
    else:
        result = {
            "installation": str(ROOT),
            "model_name": "Qwen3.6-35B-A3B 4bit",
            "omp": shutil.which("omp"),
            "codex": shutil.which("codex"),
            "local_runtime": (STATE / "venv/bin/python").exists(),
            "model_shards": len(list(LOCAL_MODEL.glob("model-*.safetensors"))),
            "model_verified": (STATE / "download/verified.json").exists(),
            "coordinator": PROFILES["coordinator"],
            "profiles": PROFILES,
            "credentials": "managed by OMP / Codex CLI; never read by AgentMesh",
        }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result.get("status") == "incomplete":
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
