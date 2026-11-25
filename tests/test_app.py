"""Queue and API tests use a fake engine; no GPU or model download is involved."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from jobs import JobManager
from storage import Store, digest_file, output_paths, prepare_settings, read_cache, save_description, scan_folder

PRESETS = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))


class FakeEngine:
    def __init__(self, block=False, fail_names=(), load_error=False):
        self.loads = []
        self.calls = []
        self.unloads = 0
        self.fail_names = set(fail_names)
        self.load_error = load_error
        self.entered = threading.Event()
        self.gate = threading.Event()
        if not block:
            self.gate.set()

    def load(self, path):
        self.loads.append(path)
        if self.load_error:
            raise RuntimeError("Unsupported test model")

    def describe(self, path, prompt, system, max_tokens):
        self.calls.append(Path(path).name)
        self.entered.set()
        if not self.gate.wait(8):
            raise RuntimeError("Test gate timed out")
        if Path(path).name in self.fail_names:
            raise ValueError("Test corrupt input")
        return "Description of " + Path(path).name

    def unload(self):
        self.unloads += 1


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="caption-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.model = self.root / "fake.safetensors"
        self.model.write_bytes(b"fake-test-checkpoint")
        self.config = {"runtime_directory": str(self.root), "default_model": str(self.model),
                       "default_folder": str(self.images), "port": 8799}
        self.store = Store(self.root / "batches.sqlite3")

    def image(self, name="one.png"):
        path = self.images / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 30), "#849b96").save(path)
        return path

    def values(self, preset="pose", **kwargs):
        p = next(p for p in PRESETS if p["id"] == preset)
        result = dict(folder=str(self.images), recursive=True, preset=preset,
            prompt=p["prompt"], system_prompt=p["system_prompt"], model_path=str(self.model),
            max_tokens=p["max_tokens"], output_label=p["label"], output_directory="",
            write_txt=True, force=False, keep_loaded=False)
        result.update(kwargs)
        return result

    def settings(self, preset="pose", **kwargs):
        return prepare_settings(self.values(preset, **kwargs), PRESETS)

    def job(self, settings=None):
        return self.store.create(settings or self.settings(), scan_folder(self.images)[1])

    def manager(self, engine):
        manager = JobManager(self.store, self.root, engine=engine)
        manager.start()
        self.addCleanup(manager.close)
        self.addCleanup(engine.gate.set)
        return manager

    def wait(self, job_id, statuses=("completed",), timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.store.job(job_id)
            if job["status"] in statuses:
                return job
            time.sleep(0.02)
        self.fail("Batch did not reach expected state: " + str(self.store.job(job_id)))


class StorageTests(Fixtures):
    def test_scan_nested_paths_and_non_images(self):
        self.image("nested/image.PNG")
        self.image("image.png")
        (self.images / "image.png.pose.json").write_text("{}")
        self.assertEqual(len(scan_folder(self.images)[1]), 2)
        self.assertEqual(len(scan_folder(self.images, False)[1]), 1)
        with self.assertRaises(ValueError):
            scan_folder("relative")

    def test_sidecars_and_cache_invalidation_preserve_source(self):
        path = self.image()
        item = scan_folder(self.images)[1][0]
        sha = digest_file(path)
        settings = self.settings()
        json_path, txt_path = save_description(item, settings, sha, "A seated figure.")
        self.assertEqual(json_path.name, "one.png.pose.json")
        self.assertEqual(txt_path.read_text(encoding="utf-8"), "A seated figure.\n")
        self.assertEqual(digest_file(path), sha)
        self.assertIsNotNone(read_cache(json_path, sha, settings))
        for changed in [self.settings(prompt="Different instruction"),
                        self.settings(max_tokens=128)]:
            self.assertIsNone(read_cache(json_path, sha, changed))
        self.assertIsNone(read_cache(json_path, "changed-image", settings))
        self.model.write_bytes(b"different-checkpoint")
        self.assertIsNone(read_cache(json_path, sha, self.settings()))

    def test_legacy_pose_cache_and_modified_pose_separation(self):
        path = self.image()
        item = scan_folder(self.images)[1][0]
        settings = self.settings()
        json_path, _ = save_description(item, settings, digest_file(path), "Standing.")
        record = json.loads(json_path.read_text())
        del record["generation_hash"]
        json_path.write_text(json.dumps(record))
        self.assertIsNotNone(read_cache(json_path, digest_file(path), settings))
        self.assertEqual(self.settings(prompt="Custom pose")["output_label"], "pose-custom")
        self.assertEqual(self.settings(max_tokens=500)["output_label"], "pose-custom")
        self.assertIsNone(read_cache(json_path, digest_file(path), self.settings("composition")))

    def test_separate_outputs_and_corrupt_cache(self):
        path = self.image("sub/item.png")
        item = scan_folder(self.images)[1][0]
        settings = self.settings("outfit", output_directory=str(self.root / "results"))
        out, _ = output_paths(item, settings)
        self.assertEqual(out, self.root / "results" / "sub" / "item.png.outfit.json")
        out.parent.mkdir(parents=True)
        out.write_text("broken json")
        self.assertIsNone(read_cache(out, digest_file(path), settings))
        with self.assertRaises(ValueError):
            output_paths({"path": str(path), "relative": "../escape.png"}, settings)
        with self.assertRaises(ValueError):
            self.settings(output_label="../escape")

    def test_restart_recovery_preserves_finished_items(self):
        self.image("one.png")
        self.image("two.png")
        job = self.job()
        self.store.next_job()
        items = self.store.items(job)
        self.store.update_item(items[0]["id"], status="done", caption="Saved")
        self.store.update_item(items[1]["id"], status="running")
        recovered = Store(self.store.path)
        self.assertEqual(recovered.job(job)["status"], "paused")
        self.assertEqual([i["status"] for i in recovered.items(job)], ["done", "pending"])
        self.assertEqual(recovered.items(job)[0]["caption"], "Saved")


class WorkerTests(Fixtures):
    def test_one_model_load_for_batch_and_cache_only_rerun(self):
        for name in ["one.png", "two.png", "three.png"]:
            self.image(name)
        engine = FakeEngine()
        manager = self.manager(engine)
        first = self.job()
        self.assertEqual(self.wait(first)["counts"], {"done": 3})
        self.assertEqual(len(engine.loads), 1)
        second = self.job()
        manager.wake.set()
        self.assertEqual(self.wait(second)["counts"], {"cached": 3})
        self.assertEqual(len(engine.calls), 3)
        self.assertEqual(len(engine.loads), 1)

    def test_pause_finishes_current_image_then_resume(self):
        for name in ["one.png", "two.png", "three.png"]:
            self.image(name)
        engine = FakeEngine(block=True)
        manager = self.manager(engine)
        job = self.job()
        manager.wake.set()
        self.assertTrue(engine.entered.wait(4))
        manager.action(job, "pause")
        self.assertEqual(self.store.job(job)["status"], "pausing")
        engine.gate.set()
        paused = self.wait(job, ("paused",))
        self.assertEqual(paused["counts"], {"done": 1, "pending": 2})
        manager.action(job, "resume")
        self.assertEqual(self.wait(job)["counts"], {"done": 3})
        self.assertEqual(len(engine.calls), 3)

    def test_cancel_retains_outputs_and_can_resume(self):
        self.image("one.png")
        self.image("two.png")
        engine = FakeEngine(block=True)
        manager = self.manager(engine)
        job = self.job()
        manager.wake.set()
        self.assertTrue(engine.entered.wait(4))
        manager.action(job, "cancel")
        engine.gate.set()
        cancelled = self.wait(job, ("cancelled",))
        self.assertEqual(cancelled["counts"], {"done": 1, "pending": 1})
        manager.action(job, "resume")
        self.assertEqual(self.wait(job)["counts"], {"done": 2})

    def test_corrupt_image_does_not_stop_batch_and_retry_only_failed(self):
        self.image("one.png")
        self.image("two.png")
        engine = FakeEngine(fail_names=["one.png"])
        manager = self.manager(engine)
        job = self.job()
        result = self.wait(job, ("completed_with_errors",))
        self.assertEqual(result["counts"], {"failed": 1, "done": 1})
        engine.fail_names.clear()
        manager.action(job, "resume")
        self.assertEqual(self.wait(job)["counts"], {"done": 2})
        self.assertEqual(engine.calls.count("two.png"), 1)

    def test_model_load_failure_preserves_pending_images(self):
        self.image()
        engine = FakeEngine(load_error=True)
        self.manager(engine)
        job = self.job()
        result = self.wait(job, ("failed",))
        self.assertEqual(result["counts"], {"pending": 1})
        self.assertIn("Could not load", result["error"])

    def test_source_changed_during_inference_is_not_saved(self):
        path = self.image()
        engine = FakeEngine(block=True)
        manager = self.manager(engine)
        job = self.job()
        manager.wake.set()
        self.assertTrue(engine.entered.wait(4))
        Image.new("RGB", (20, 30), "red").save(path)
        engine.gate.set()
        result = self.wait(job, ("completed_with_errors",))
        self.assertEqual(result["counts"], {"failed": 1})
        self.assertFalse(path.with_name(path.name + ".pose.json").exists())

    def test_hundreds_of_images_are_queued_and_saved(self):
        for i in range(250):
            self.image(f"image-{i:03}.png")
        engine = FakeEngine()
        self.manager(engine)
        job = self.job()
        self.assertEqual(self.wait(job, timeout=25)["counts"], {"done": 250})
        self.assertEqual(len(engine.loads), 1)
        self.assertEqual(len(self.store.items(job, 240, 24)), 10)
        self.assertEqual(len(list(self.images.glob("*.pose.json"))), 250)


class ApiTests(Fixtures):
    def client(self):
        application = create_app(config=self.config, data_directory=self.root / "api-data", engine=FakeEngine())
        client = TestClient(application, base_url="http://127.0.0.1:8799")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def connect(self, client):
        self.assertEqual(client.get("/").status_code, 200)
        bootstrap = client.get("/api/bootstrap").json()
        return {"X-CSRF-Token": bootstrap["csrf"]}

    def test_local_session_and_origin_checks(self):
        client = self.client()
        self.assertEqual(client.get("/api/bootstrap").status_code, 401)
        self.assertEqual(client.get("/api/health").status_code, 200)
        headers = self.connect(client)
        self.assertEqual(client.post("/api/scan", json={"folder": str(self.images)}).status_code, 403)
        self.assertEqual(client.post("/api/scan", json={"folder": str(self.images)},
            headers={**headers, "Origin": "https://example.invalid"}).status_code, 403)
        self.assertEqual(client.get("/api/health", headers={"Host": "malicious.invalid"}).status_code, 403)
        self.assertEqual(client.get("/api/jobs/missing").status_code, 404)

    def test_scan_preview_batch_results_and_exports(self):
        self.image("=formula.png")
        self.image("nested/other.png")
        client = self.client()
        headers = self.connect(client)
        scan = client.post("/api/scan", json={"folder": str(self.images)}, headers=headers).json()
        self.assertEqual(scan["total"], 2)
        preview = client.get("/api/scans/" + scan["id"] + "/items").json()
        self.assertEqual(client.get(preview["items"][0]["thumbnail"]).headers["content-type"], "image/jpeg")
        response = client.post("/api/jobs", json=self.values("composition"), headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = client.get("/api/jobs/" + job["id"]).json()
            if result["status"] == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(result["counts"], {"done": 2})
        items = client.get("/api/jobs/" + job["id"] + "/items?limit=1").json()
        self.assertEqual(items["total"], 2)
        self.assertEqual(len(items["items"]), 1)
        self.assertEqual(client.get("/api/items/" + str(items["items"][0]["id"]) + "/image").status_code, 200)
        export = client.get("/api/jobs/" + job["id"] + "/export?format=json").json()
        self.assertEqual(len(export["images"]), 2)
        csv = client.get("/api/jobs/" + job["id"] + "/export?format=csv")
        self.assertIn("'=formula.png", csv.text)
        self.assertIn("attachment", csv.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
