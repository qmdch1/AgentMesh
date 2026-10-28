import importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "mesh", Path(__file__).resolve().parents[1] / "scripts/agentmesh/runtime.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def task(ident, **kw):
    return dict(
        id=ident,
        profile="design",
        instruction="Work on assigned part",
        acceptance=["correct result"],
        depends_on=[],
        write_paths=[],
        read_paths=[],
        context_files=[],
        checks=[],
        **kw,
    )


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir()
        self.state = Path(self.tmp.name) / "state"
        self.patch = patch.object(m, "STATE", self.state)
        self.patch.start()
        m.CANCEL.clear()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def plan(self, *tasks):
        return dict(
            workspace=str(self.ws),
            tasks=list(tasks),
            common_context="shared constraints",
        )

    def test_reject_cycles_unknown_profiles_escapes_and_missing_checks(self):
        for change in [
            dict(profile="absent"),
            dict(depends_on=["missing"]),
            dict(write_paths=["../oops"]),
            dict(write_paths=["a.txt"]),
            dict(profile="local"),
        ]:
            t = task("a")
            t.update(change)
            with self.assertRaises(ValueError):
                m.validate(self.plan(t))
        a = task("a")
        b = task("b")
        a["depends_on"] = ["b"]
        b["depends_on"] = ["a"]
        with self.assertRaises(ValueError):
            m.validate(self.plan(a, b))

    def test_real_check_failure_blocks_dependent(self):
        a = task("a")
        a.update(write_paths=["a.txt"], checks=[["/usr/bin/false"]])
        b = task("b")
        b["depends_on"] = ["a"]

        def fake(cmd, cwd, log, timeout, env):
            Path(log).write_text(
                json.dumps(
                    dict(
                        type="message_end",
                        message=dict(
                            role="assistant",
                            model="claude-sonnet-5-5",
                            content=[dict(type="text", text="done")],
                        ),
                    )
                )
            )
            return 0

        state = m.run(self.plan(a, b), executor=fake)
        self.assertEqual(state["results"]["a"]["status"], "failed")
        self.assertEqual(state["results"]["b"]["status"], "blocked")
        self.assertEqual(state["status"], "incomplete")

    def test_success_resume_reuses_work_and_revision_invalidates_dependents(self):
        a = task("a")
        b = task("b")
        b["depends_on"] = ["a"]
        seen = []

        def fake(t, p, d, results, executor):
            seen.append(t["id"])
            return dict(status="passed", result=t["id"])

        plan = self.plan(a, b)
        with patch.object(m, "worker", fake):
            state = m.run(plan)
            self.assertEqual(seen, ["a", "b"])
            seen.clear()
            m.run(plan, state["run_id"])
            self.assertEqual(seen, [])
            a["instruction"] = "revised"
            m.run(plan, state["run_id"])
            self.assertEqual(seen, ["a", "b"])

    def test_failed_task_does_not_reset_attempt_budget(self):
        a = task("a")
        with patch.object(
            m, "worker", return_value=dict(status="failed", error="quota")
        ):
            state = m.run(self.plan(a))
            for _ in range(4):
                state = m.run(self.plan(a), state["run_id"])
        self.assertEqual(state["attempts"]["a"], 3)
        self.assertEqual(state["status"], "incomplete")

    def test_parser_detects_provider_error_even_with_zero_exit(self):
        log = Path(self.tmp.name) / "log"
        log.write_text(
            json.dumps(
                dict(
                    type="message_end",
                    message=dict(
                        role="assistant",
                        model="gpt-6.1-sol",
                        stopReason="error",
                        errorMessage="usage_limit_reached",
                        content=[],
                    ),
                )
            )
        )
        final, error, _, _ = m.parse_worker(log)
        self.assertEqual(error, "usage_limit_reached")
        self.assertFalse(final)

    def test_unscoped_write_is_failed(self):
        def fake(cmd, cwd, log, timeout, env):
            (cwd / "outside.txt").write_text("oops")
            Path(log).write_text(
                json.dumps(
                    dict(
                        type="message_end",
                        message=dict(
                            role="assistant",
                            model="claude-sonnet-5-5",
                            content=[dict(type="text", text="done")],
                        ),
                    )
                )
            )
            return 0

        state = m.run(self.plan(task("a")), executor=fake)
        self.assertEqual(state["results"]["a"]["scope_violations"], ["outside.txt"])
        self.assertEqual(state["status"], "incomplete")

    def test_context_does_not_include_unrelated_source(self):
        (self.ws / "needed.txt").write_text("relevant")
        (self.ws / "unrelated.txt").write_text("never include this")
        t = task("a")
        t["context_files"] = ["needed.txt"]

        def fake(cmd, cwd, log, timeout, env):
            payload = json.loads(Path(env["AGENTMESH_WORKER_SPEC"]).read_text())
            self.assertEqual(payload["context_files"], {"needed.txt": "relevant"})
            self.assertNotIn("never include this", json.dumps(payload))
            Path(log).write_text(
                json.dumps(
                    dict(
                        type="message_end",
                        message=dict(
                            role="assistant",
                            model="claude-sonnet-5-5",
                            content=[dict(type="text", text="done")],
                        ),
                    )
                )
            )
            return 0

        self.assertEqual(m.run(self.plan(t), executor=fake)["status"], "passed")

    def test_writers_are_not_concurrent(self):
        import threading, time

        active = 0
        maximum = 0
        lock = threading.Lock()

        def fake(t, p, d, results, executor):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.04)
            with lock:
                active -= 1
            return dict(status="passed")

        a = task("a")
        a.update(write_paths=["a"], checks=[["true"]])
        b = task("b")
        b.update(write_paths=["b"], checks=[["true"]])
        with patch.object(m, "worker", fake):
            m.run(self.plan(a, b))
        self.assertEqual(maximum, 1)

    def test_readonly_independent_parts_are_concurrent(self):
        import threading

        barrier = threading.Barrier(2)

        def fake(t, p, d, results, executor):
            barrier.wait(2)
            return dict(status="passed")

        with patch.object(m, "worker", fake):
            self.assertEqual(m.run(self.plan(task("a"), task("b")))["status"], "passed")

    def test_process_timeout_stops_worker(self):
        import sys, time

        start = time.monotonic()
        code = m.execute(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            self.ws,
            Path(self.tmp.name) / "timeout.log",
            timeout=0.2,
        )
        self.assertEqual(code, 124)
        self.assertLess(time.monotonic() - start, 3)
        self.assertFalse(m.CHILDREN)

    def test_resume_cannot_extend_original_budget(self):
        a = task("a")
        plan = self.plan(a)
        plan["run_timeout"] = 60
        with patch.object(
            m, "worker", return_value=dict(status="failed", error="fixture")
        ):
            state = m.run(plan)
        p = self.state / "runs" / state["run_id"] / "state.json"
        state["created"] -= 61
        m.atomic(p, state)
        plan["run_timeout"] = 7200
        with patch.object(m, "worker") as worker:
            result = m.run(plan, state["run_id"])
            worker.assert_not_called()
        self.assertEqual(result["run_timeout"], 60)

    def test_local_rejects_visual_input(self):
        t = task("a")
        t.update(profile="local", scope_confirmed=True, context_images=["screen.png"])
        with self.assertRaises(ValueError):
            m.validate(self.plan(t))

    def test_native_codex_events_success_and_failure(self):
        log = Path(self.tmp.name) / "native.jsonl"
        log.write_text(
            "\n".join(
                json.dumps(x)
                for x in [
                    dict(
                        type="item.completed",
                        item=dict(type="agent_message", text="native result"),
                    ),
                    dict(type="turn.completed", usage=dict(output_tokens=3)),
                ]
            )
        )
        result, error, model, usage = m.parse_codex(log, "gpt-6.1-sol")
        self.assertEqual(result, "native result")
        self.assertIsNone(error)
        self.assertEqual(model, "gpt-6.1-sol")
        log.write_text(
            json.dumps(
                dict(type="turn.failed", error=dict(message="usage_limit_reached"))
            )
        )
        self.assertEqual(m.parse_codex(log, "gpt-6.1-sol")[1], "usage_limit_reached")

    def test_successful_run_rejects_workspace_change(self):
        with patch.object(m, "worker", return_value=dict(status="passed")):
            state = m.run(self.plan(task("a")))
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        plan = self.plan(task("a"))
        plan["workspace"] = str(other)
        with self.assertRaises(ValueError):
            m.run(plan, state["run_id"])

    def test_symlink_escape_rejected(self):
        outside = Path(self.tmp.name) / "external"
        outside.mkdir()
        (self.ws / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            m.inside(self.ws, "link/data")

    def test_native_cli_explicit_profile_fast_and_stdin(self):
        t = task("a")
        t["profile"] = "code"

        def fake(cmd, cwd, log, timeout, env):
            self.assertIn("gpt-6.1-sol", cmd)
            self.assertIn('service_tier="fast"', cmd)
            self.assertEqual(cmd[-1], "-")
            self.assertTrue(Path(env["AGENTMESH_STDIN"]).is_file())
            Path(log).write_text(
                json.dumps(
                    dict(
                        type="item.completed",
                        item=dict(type="agent_message", text="OK"),
                    )
                )
            )
            return 0

        result = m.run(self.plan(t), executor=fake)
        self.assertEqual(result["status"], "passed")
        self.assertIn("CLI argument", result["results"]["a"]["model_source"])

    def test_local_input_limit_returns_failure_before_inference(self):
        t = task("a")
        t.update(profile="local", scope_confirmed=True)
        plan = self.plan(t)
        plan["common_context"] = "x" * 25000
        with patch.object(m, "execute") as invoke:
            result = m.run(plan)
            invoke.assert_not_called()
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("context exceeds", result["results"]["a"]["error"])

    def test_checks_cannot_silently_modify_outside_scope(self):
        import sys

        t = task("a")
        t.update(
            write_paths=["allowed.txt"],
            checks=[[sys.executable, "-c", 'open("outside.txt","w").write("bad")']],
        )

        def fake(cmd, cwd, log, timeout, env):
            Path(log).write_text(
                json.dumps(
                    dict(
                        type="message_end",
                        message=dict(
                            role="assistant",
                            model="claude-sonnet-5-5",
                            content=[dict(type="text", text="done")],
                        ),
                    )
                )
            )
            return 0

        result = m.run(self.plan(t), executor=fake)
        self.assertEqual(result["results"]["a"]["scope_violations"], ["outside.txt"])
        self.assertEqual(result["status"], "incomplete")

    def test_guard_stops_orphans_after_parent_exit(self):
        import subprocess, sys

        guard = m.ROOT / "scripts/agentmesh/process_guard.py"
        child = "import time; time.sleep(30)"
        driver = f'import subprocess,sys,time; p=subprocess.Popen([sys.executable,{str(guard)!r},sys.executable,"-c",{child!r}],start_new_session=True); print(p.pid,flush=True); time.sleep(.2)'
        p = subprocess.Popen(
            [sys.executable, "-c", driver], stdout=subprocess.PIPE, text=True
        )
        output, _ = p.communicate(timeout=5)
        pid = output.strip().splitlines()[0]
        status = subprocess.run(
            ["ps", "-p", pid, "-o", "stat="], capture_output=True, text=True
        ).stdout.strip()
        self.assertTrue(not status or status.startswith("Z"), status)

    def test_changed_input_invalidates_cached_success_and_dependents(self):
        (self.ws / "input.txt").write_text("first")
        a = task("a")
        a["context_files"] = ["input.txt"]
        b = task("b")
        b["depends_on"] = ["a"]
        seen = []

        def fake(cmd, cwd, log, timeout, env):
            seen.append(
                json.loads(Path(env["AGENTMESH_WORKER_SPEC"]).read_text())["task"]["id"]
            )
            Path(log).write_text(
                json.dumps(
                    dict(
                        type="message_end",
                        message=dict(
                            role="assistant",
                            model="claude-sonnet-5-5",
                            content=[dict(type="text", text="done")],
                        ),
                    )
                )
            )
            return 0

        plan = self.plan(a, b)
        state = m.run(plan, executor=fake)
        seen.clear()
        m.run(plan, state["run_id"], executor=fake)
        self.assertEqual(seen, [])
        (self.ws / "input.txt").write_text("changed")
        m.run(plan, state["run_id"], executor=fake)
        self.assertEqual(seen, ["a", "b"])

    def test_common_constraints_change_invalidates_success(self):
        plan = self.plan(task("a"))
        with patch.object(m, "worker", return_value=dict(status="passed")):
            state = m.run(plan)
        plan["common_context"] = "new constraint"
        with patch.object(m, "worker", return_value=dict(status="passed")) as worker:
            m.run(plan, state["run_id"])
            worker.assert_called_once()

    def test_snapshot_records_large_files_output_directories_and_symlinks(self):
        (self.ws / "outputs").mkdir()
        (self.ws / "outputs/a.txt").write_text("first")
        with (self.ws / "large.bin").open("wb") as stream:
            stream.truncate(17 * 1024 * 1024)
        before = m.snapshot(self.ws)
        (self.ws / "outputs/a.txt").write_text("changed")
        (self.ws / "link").symlink_to("outputs")
        with (self.ws / "large.bin").open("r+b") as stream:
            stream.write(b"X")
        after = m.snapshot(self.ws)
        self.assertNotEqual(before["large.bin"], after["large.bin"])
        self.assertNotEqual(before["outputs/a.txt"], after["outputs/a.txt"])
        self.assertIn("symlink:", after["link"])

    def test_worker_receives_remaining_run_budget(self):
        plan = self.plan(task("a"))
        plan["run_timeout"] = 1
        plan["task_timeout"] = 600

        def fake(t, p, d, results, executor):
            self.assertGreater(p["task_timeout"], 0)
            self.assertLessEqual(p["task_timeout"], 1)
            return dict(status="passed")

        with patch.object(m, "worker", fake):
            self.assertEqual(m.run(plan)["status"], "passed")

    def test_normalize_paths_without_allowing_workspace_wide_writes(self):
        t = task("a")
        t.update(
            context_files=["./file.txt"],
            read_paths=["."],
            write_paths=["sub/../file.txt"],
            checks=[["true"]],
        )
        m.validate(self.plan(t))
        self.assertEqual(t["context_files"], ["file.txt"])
        self.assertEqual(t["write_paths"], ["file.txt"])
        self.assertTrue(m.allowed("sub/a.txt", t["read_paths"]))
        t["write_paths"] = ["."]
        with self.assertRaises(ValueError):
            m.validate(self.plan(t))

    def test_local_uses_scoped_line_writer_without_shell_or_raw_write(self):
        t = task("local")
        t.update(
            profile="local",
            scope_confirmed=True,
            write_paths=["label.txt"],
            checks=[["true"]],
        )

        def fake(cmd, cwd, log, timeout, env):
            tools = cmd[cmd.index("--tools") + 1].split(",")
            self.assertIn("mesh_write", tools)
            for name in ["bash", "write", "edit"]:
                self.assertNotIn(name, tools)
            Path(log).write_text(
                json.dumps(
                    dict(
                        type="message_end",
                        message=dict(
                            role="assistant",
                            model="Qwen3.6-35B-A3B 4bit",
                            content=[dict(type="text", text="done")],
                        ),
                    )
                )
            )
            return 0

        self.assertEqual(m.run(self.plan(t), executor=fake)["status"], "passed")

    def test_status_without_run_id_is_scoped_to_current_project(self):
        other = Path(self.tmp.name) / "other-project"
        other.mkdir()
        with patch.object(m, "worker", return_value={"status": "passed"}):
            first = m.run(self.plan(task("a")))
            plan = self.plan(task("b"))
            plan["workspace"] = str(other)
            second = m.run(plan)
        self.assertEqual(m.status(workspace=self.ws)["run_id"], first["run_id"])
        self.assertEqual(m.status(workspace=other)["run_id"], second["run_id"])
        self.assertEqual(
            m.status(workspace=Path(self.tmp.name) / "unused")["status"], "no_runs"
        )


if __name__ == "__main__":
    unittest.main()
