#!/usr/bin/env python3
"""Real OMP/model smoke tests in disposable project-local fixtures."""

import argparse, importlib.util, json, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "mesh_runtime", ROOT / "scripts/agentmesh/runtime.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--local", action="store_true")
    p.add_argument("--code", action="store_true")
    a = p.parse_args()
    ws = ROOT / ".agentmesh/fixtures" / ("live-" + uuid.uuid4().hex[:8])
    ws.mkdir(parents=True)
    (ws / "numbers.txt").write_text("4 7 9\n")
    (ws / "label.txt").write_text("연결\n")
    tasks = [
        dict(
            id="analyze",
            profile="design",
            instruction="Read numbers.txt and return SUM=20.",
            acceptance=["SUM=20"],
            context_files=["numbers.txt"],
        ),
        dict(
            id="edit",
            profile="local" if a.local else "design",
            instruction=(
                'Use mesh_write to replace label.txt with lines=["연결하기"], final_newline=true: exactly 13 UTF-8 bytes.'
                if a.local
                else "Use your native edit/write tool to replace label.txt with 연결하기 plus one LF (codepoint 10), exactly 13 UTF-8 bytes."
            )
            + " Only edit label.txt. Report checks as pending for the runner; do not run bash.",
            acceptance=["label.txt has exactly 연결하기 plus LF, 13 UTF-8 bytes"],
            context_files=["label.txt"],
            write_paths=["label.txt"],
            scope_confirmed=True,
            checks=[
                [
                    "/usr/bin/python3",
                    "-c",
                    'assert open("label.txt","rb").read()==("연결하기"+chr(10)).encode("utf-8")',
                ]
            ],
        ),
        dict(
            id="integrate",
            profile="code" if a.code else "design",
            instruction='Read predecessor results, write result.json with exactly {"sum":20,"label":"연결하기"}. Only edit result.json. Do not run bash.',
            acceptance=["result.json matches"],
            depends_on=["analyze", "edit"],
            context_files=["label.txt"],
            write_paths=["result.json"],
            checks=[
                [
                    "/usr/bin/python3",
                    "-c",
                    'import json; assert json.load(open("result.json"))=={"sum":20,"label":"연결하기"}',
                ]
            ],
        ),
    ]
    state = m.run(
        dict(
            workspace=str(ws),
            tasks=tasks,
            common_context="Synthetic test only. No other files may change.",
            task_timeout=240,
            run_timeout=1200,
        )
    )
    report = {
        "fixture": str(ws.relative_to(ROOT)),
        "run_id": state["run_id"],
        "status": state["status"],
        "tasks": {
            k: {
                "status": v["status"],
                "model": v.get("model"),
                "checks": v.get("checks", []),
                "error": v.get("error"),
            }
            for k, v in state["results"].items()
        },
    }
    (ROOT / ".agentmesh/latest-smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if state["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
