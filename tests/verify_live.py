"""Explicit integration test against the running app, using actual local vision inference."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
import urllib.request
import http.cookiejar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import digest_file, output_paths, prepare_settings, read_cache, scan_folder

VERIFY = ROOT / "verification"
VERIFY.mkdir(exist_ok=True)
MANIFEST = VERIFY / "live_run.json"
config = json.loads((ROOT / "config.json").read_text())
presets = json.loads((ROOT / "presets.json").read_text())
base = "http://127.0.0.1:" + str(config["port"])
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
opener.open(base + "/").read()
bootstrap = json.load(opener.open(base + "/api/bootstrap"))


def api(path, value=None):
    data = None if value is None else json.dumps(value).encode()
    request = urllib.request.Request(base + path, data=data,
        headers={"Content-Type": "application/json", "X-CSRF-Token": bootstrap["csrf"]})
    return json.load(opener.open(request, timeout=30))


def values(folder, preset, **extra):
    p = next(p for p in presets if p["id"] == preset)
    result = dict(folder=str(folder), recursive=True, preset=preset,
        prompt=p["prompt"], system_prompt=p["system_prompt"], model_path=config["default_model"],
        max_tokens=p["max_tokens"], output_label=p["label"], output_directory="",
        write_txt=True, force=False, keep_loaded=False)
    result.update(extra)
    return result


def start():
    if MANIFEST.exists():
        raise RuntimeError("This verification already has a manifest. Use status or finish.")
    sample_folder = ROOT / "Examples" / "Sample images"
    sample_folder.mkdir(parents=True, exist_ok=True)
    sources = [
        (Path(config["default_folder"]) / "page 061 image 003.png", "pose-reference.png"),
        (Path(r"C:\Users\xande\Downloads\Midnight Navy Lace Corset Dress.png"), "navy-dress.png"),
        (Path(r"C:\Users\xande\Downloads\Base Master.png"), "character-reference.png"),
    ]
    source_hashes = {}
    for source, name in sources:
        source_hashes[str(source)] = digest_file(source)
        shutil.copy2(source, sample_folder / name)
    samples = {str(p): digest_file(p) for p in sample_folder.iterdir() if p.is_file()}
    manifest = {"started_at": time.time(), "source_hashes": source_hashes,
                "sample_hashes": samples, "jobs": {}, "real_model": config["default_model"]}
    legacy_values = values(config["default_folder"], "pose", write_txt=False)
    settings = prepare_settings(legacy_values, presets)
    _, files, _ = scan_folder(config["default_folder"])
    valid = [item for item in files if read_cache(output_paths(item, settings)[0],
                                               digest_file(item["path"]), settings)]
    manifest["existing_pose_cache_preflight"] = {"images": len(files), "matching": len(valid)}
    # Never silently turn this compatibility check into hundreds of fresh inference requests.
    if len(valid) == len(files):
        manifest["jobs"]["existing_pose_cache"] = api("/api/jobs", legacy_values)["id"]
    for preset, keep in [("composition", True), ("outfit", False)]:
        manifest["jobs"][preset] = api("/api/jobs", values(sample_folder, preset, keep_loaded=keep))["id"]
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def status():
    manifest = json.loads(MANIFEST.read_text())
    result = {"worker": api("/api/state")["worker"], "jobs": {}}
    for name, job_id in manifest["jobs"].items():
        job = api("/api/jobs/" + job_id)
        result["jobs"][name] = {key: job[key] for key in ("id", "status", "counts", "current_file", "error")}
    print(json.dumps(result, indent=2))


def finish():
    manifest = json.loads(MANIFEST.read_text())
    jobs = {name: api("/api/jobs/" + job_id) for name, job_id in manifest["jobs"].items()}
    if any(job["status"] != "completed" for job in jobs.values()):
        status()
        raise RuntimeError("Wait for all verification batches to complete before finishing.")
    checks = {
        "originals_unchanged": all(digest_file(path) == sha for path, sha in manifest["source_hashes"].items()),
        "samples_unchanged": all(digest_file(path) == sha for path, sha in manifest["sample_hashes"].items()),
        "three_compositions_generated": jobs["composition"]["counts"] == {"done": 3},
        "three_outfits_generated": jobs["outfit"]["counts"] == {"done": 3},
    }
    if "existing_pose_cache" in jobs:
        checks["all_existing_pose_descriptions_reused"] = jobs["existing_pose_cache"]["counts"] == {
            "cached": manifest["existing_pose_cache_preflight"]["images"]}
    results = {}
    for name, job in jobs.items():
        exported = api("/api/jobs/" + job["id"] + "/export")
        (VERIFY / (name + "_batch.json")).write_text(json.dumps(exported, indent=2), encoding="utf-8")
        if name != "existing_pose_cache":
            results[name] = exported["images"]
            checks[name + "_outputs_match_history"] = all(
                json.loads(Path(item["output_json"]).read_text(encoding="utf-8"))["caption"] == item["caption"]
                and Path(item["output_txt"]).read_text(encoding="utf-8").strip() == item["caption"]
                for item in exported["images"])
    sample_folder = ROOT / "Examples" / "Sample images"
    rerun = api("/api/jobs", values(sample_folder, "composition"))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        rerun = api("/api/jobs/" + rerun["id"])
        if rerun["status"] == "completed":
            break
        time.sleep(0.2)
    checks["repeat_batch_reuses_all_three"] = rerun["counts"] == {"cached": 3}
    report = {"checks": checks, "all_passed": all(checks.values()),
        "total_real_descriptions": 6, "generated_results": results, "cache_repeat_job": rerun["id"],
        "comfyui_server_used": False, "test_completed_at": time.time(),
        "note": "250-image queue test uses a mock engine; existing 200-image pose batch uses real cached captions."}
    (VERIFY / "live_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"checks": checks, "all_passed": report["all_passed"], "report": str(VERIFY / "live_validation.json")}, indent=2))
    if not report["all_passed"]:
        raise RuntimeError("A live validation check failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "status", "finish"])
    action = parser.parse_args().action
    {"start": start, "status": status, "finish": finish}[action]()
