import threading
import time

from engine import VisionEngine
from storage import atomic_text, digest_file, now, output_paths, read_cache, save_description


class JobManager:
    def __init__(self, store, runtime_directory, engine=None):
        self.store = store
        self.engine = engine or VisionEngine(runtime_directory)
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.release_requested = threading.Event()
        self.lock = threading.RLock()
        self.active_job = None
        self.phase = "idle"
        self.loaded_model = ""
        self.loaded_signature = ""
        self.thread = threading.Thread(target=self.loop, daemon=True, name="caption-worker")

    def start(self):
        self.thread.start()

    def close(self):
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=5)

    def state(self):
        with self.lock:
            return {"active_job": self.active_job, "phase": self.phase, "loaded_model": self.loaded_model}

    def set_state(self, **values):
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def release(self):
        self.set_state(phase="releasing")
        try:
            self.engine.unload()
        finally:
            self.set_state(loaded_model="", loaded_signature="", phase="idle")
            self.release_requested.clear()

    def action(self, job_id, action):
        with self.lock:
            job = self.store.job(job_id)
            if job is None:
                raise ValueError("Batch not found.")
            status = job["status"]
            if action == "resume":
                if status not in {"paused", "cancelled", "failed", "completed_with_errors"}:
                    raise ValueError("This batch cannot be resumed in its current state.")
                self.store.resume(job_id)
            elif action == "pause":
                if status not in {"queued", "running"}:
                    raise ValueError("Only queued or running batches can be paused.")
                self.store.update_job(job_id, status="pausing" if status == "running" else "paused")
            elif action == "cancel":
                if status not in {"queued", "running", "pausing", "paused"}:
                    raise ValueError("This batch is already finished.")
                self.store.update_job(job_id, status="cancelling" if status in {"running", "pausing"} else "cancelled")
            else:
                raise ValueError("Unknown batch action.")
        self.wake.set()

    def loop(self):
        while not self.stopping.is_set():
            with self.lock:
                job_id = self.store.next_job()
                self.active_job = job_id
            if not job_id:
                if self.release_requested.is_set():
                    self.release()
                self.wake.wait(0.5)
                self.wake.clear()
                continue
            settings = self.store.job(job_id)["settings"]
            try:
                self.process(job_id, settings)
            except Exception as error:
                self.store.update_job(job_id, status="failed", error=str(error)[:2000], finished_at=now())
            finally:
                if not settings["keep_loaded"] or self.release_requested.is_set():
                    try:
                        self.release()
                    except Exception as error:
                        self.store.update_job(job_id, error="Descriptions are saved, but model cleanup failed: " + str(error)[:1500])
                self.set_state(active_job=None, phase="idle")
        self.release()

    def process(self, job_id, settings):
        while not self.stopping.is_set():
            with self.lock:
                status = self.store.job(job_id)["status"]
                if status in {"pausing", "cancelling"}:
                    self.store.update_job(job_id, status="paused" if status == "pausing" else "cancelled")
                    return
                item = self.store.next_item(job_id)
                if item is None:
                    errors = self.store.job(job_id)["counts"].get("failed", 0)
                    self.store.update_job(job_id, status="completed_with_errors" if errors else "completed", finished_at=now())
                    return
                self.store.update_item(item["id"], status="running", error="")
            try:
                self.set_state(phase="checking")
                source_hash = digest_file(item["path"])
                json_path, txt_path = output_paths(item, settings)
                cached = None if settings["force"] else read_cache(json_path, source_hash, settings)
                if cached:
                    if settings["write_txt"]:
                        atomic_text(txt_path, cached["caption"] + "\n")
                    self.store.update_item(item["id"], status="cached", caption=cached["caption"],
                        source_sha256=source_hash, output_json=str(json_path),
                        output_txt=str(txt_path) if settings["write_txt"] else "", seconds=0)
                    continue
                if self.loaded_signature != settings["model_signature"]:
                    self.set_state(phase="loading")
                    try:
                        self.engine.load(settings["model_path"])
                    except Exception as error:
                        self.store.update_item(item["id"], status="pending")
                        self.store.update_job(job_id, status="failed",
                            error="Could not load the local vision model: " + str(error)[:1500])
                        return
                    self.set_state(loaded_model=settings["model_path"], loaded_signature=settings["model_signature"])
                self.set_state(phase="describing")
                start = time.monotonic()
                caption = self.engine.describe(item["path"], settings["prompt"],
                                               settings["system_prompt"], settings["max_tokens"])
                elapsed = time.monotonic() - start
                # A changed file must not receive a caption for its previous contents.
                if digest_file(item["path"]) != source_hash:
                    raise ValueError("The image changed while it was being described. Resume to retry it.")
                save_description(item, settings, source_hash, caption)
                self.store.update_item(item["id"], status="done", caption=caption,
                    source_sha256=source_hash, output_json=str(json_path),
                    output_txt=str(txt_path) if settings["write_txt"] else "", seconds=elapsed)
            except Exception as error:
                self.store.update_item(item["id"], status="failed", error=str(error)[:1500])
                if "out of memory" in str(error).lower():
                    self.store.update_job(job_id, status="failed",
                        error="GPU memory ran out. Finish other GPU tasks, then resume this batch.")
                    self.release()
                    return
        self.store.update_job(job_id, status="paused", error="Processing stopped. Resume to continue.")
