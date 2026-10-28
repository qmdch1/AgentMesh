"""Download official model shards with resumable HTTP ranges and SHA-256 verification."""

import concurrent.futures, hashlib, json, os, sys, threading, time, urllib.request
from pathlib import Path
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / ".agentmesh/models/Qwen3.6-35B-A3B-4bit"
CACHE = ROOT / ".agentmesh/download"
CACHE.mkdir(parents=True, exist_ok=True)
REPO = "mlx-community/Qwen3.6-35B-A3B-4bit"
model_lock = json.loads((ROOT / "scripts/agentmesh/model.lock.json").read_text())
revision = model_lock["revision"]
info = HfApi().model_info(REPO, revision=revision, files_metadata=True)
revision_file = CACHE / "revision.txt"
if info.sha != revision:
    raise RuntimeError("Model revision did not match model.lock.json")
revision_file.write_text(revision)
DEST.mkdir(parents=True, exist_ok=True)
CHUNK = 32 * 1024 * 1024
lock = threading.Lock()
started = time.time()
finished = 0
jobs = []
for f in info.siblings:
    if not f.rfilename.endswith(".safetensors"):
        continue
    expected = model_lock["files"].get(f.rfilename)
    digest = f.lfs.sha256 if hasattr(f.lfs, "sha256") else f.lfs["sha256"]
    if expected != {"size": f.size, "sha256": digest}:
        raise RuntimeError("Model metadata did not match model.lock.json")
    target = DEST / f.rfilename
    if target.exists() and target.stat().st_size == f.size:
        continue
    partial = CACHE / (f.rfilename + ".partial")
    fd = os.open(partial, os.O_RDWR | os.O_CREAT, 0o600)
    marker = CACHE / (f.rfilename + ".json")
    done = set(json.loads(marker.read_text()) if marker.exists() else [])
    for n, start in enumerate(range(0, f.size, CHUNK)):
        if n not in done:
            jobs.append((f, n, start, min(start + CHUNK, f.size) - 1, fd, done, marker))


def fetch(job):
    global finished
    f, n, start, end, fd, done, marker = job
    url = f"https://huggingface.co/{REPO}/resolve/{revision}/{f.rfilename}?download=true&mesh_range={n}"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=90) as r:
                cr = r.headers.get("Content-Range", "")
                if not cr.startswith(f"bytes {start}-{end}/"):
                    raise RuntimeError("Server returned a different range")
                data = r.read(end - start + 2)
            if len(data) != end - start + 1:
                raise RuntimeError("Incomplete model chunk")
            os.pwrite(fd, data, start)
            with lock:
                done.add(n)
                tmp = marker.with_suffix(".tmp")
                tmp.write_text(json.dumps(sorted(done)))
                tmp.replace(marker)
                finished += 1
                if finished % 8 == 0:
                    print(
                        f"{finished}/{len(jobs)} chunks verified for transfer ({round(time.time() - started)}s)",
                        flush=True,
                    )
            return
        except Exception:
            if attempt == 4:
                raise
            time.sleep(min(2**attempt, 8))


with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
    list(pool.map(fetch, jobs))
for f in info.siblings:
    if not f.rfilename.endswith(".safetensors"):
        continue
    target = DEST / f.rfilename
    partial = CACHE / (f.rfilename + ".partial")
    source = partial if partial.exists() else target
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for b in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(b)
    expected = f.lfs.sha256 if hasattr(f.lfs, "sha256") else f.lfs["sha256"]
    if digest.hexdigest() != expected:
        if os.environ.get("AGENTMESH_REPAIR") == "1":
            raise RuntimeError("Repeated model checksum mismatch: " + f.rfilename)
        source.rename(CACHE / (f.rfilename + ".corrupt"))
        (CACHE / (f.rfilename + ".json")).unlink(missing_ok=True)
        os.environ["AGENTMESH_REPAIR"] = "1"
        os.execv(sys.executable, [sys.executable, __file__])
    if source != target:
        source.replace(target)
    print(f.rfilename, "SHA256 PASS", flush=True)
# Small config/tokenizer files already downloaded, and fill any missing ones at the pinned revision.
from huggingface_hub import snapshot_download

snapshot_download(
    REPO,
    revision=revision,
    local_dir=DEST,
    ignore_patterns=["*.safetensors"],
    max_workers=4,
)
(CACHE / "verified.json").write_text(
    json.dumps(
        {
            "repository": REPO,
            "revision": revision,
            "sha256_verified": True,
            "files": {
                f.rfilename: {
                    "size": f.size,
                    "sha256": f.lfs.sha256
                    if hasattr(f.lfs, "sha256")
                    else f.lfs["sha256"],
                }
                for f in info.siblings
                if f.rfilename.endswith(".safetensors")
            },
        }
    )
)
print("MODEL_DOWNLOAD_COMPLETE", flush=True)
