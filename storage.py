import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

from neutral_language import neutralize_gender

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
CHARACTER_REFERENCE_GUIDANCE = (
    "Use the supplied character reference image for the character's identity and physical appearance, "
    "overriding any conflicting character description, while following this text prompt for the pose, "
    "expression, outfit, composition, setting, lighting, and image style."
)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atomic_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def scan_folder(folder, recursive=True):
    root = Path(folder).expanduser()
    if not root.is_absolute():
        raise ValueError("Enter an absolute folder path.")
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("That image folder does not exist.")
    files, warnings, seen = [], [], set()
    with os.scandir(root):
        pass
    for directory, directories, names in os.walk(root, followlinks=False,
            onerror=lambda error: warnings.append(str(error))):
        directories[:] = [name for name in directories if not (Path(directory) / name).is_symlink()]
        for name in names:
            candidate = Path(directory) / name
            if candidate.suffix.lower() not in EXTENSIONS:
                continue
            path = candidate.resolve()
            if not path.is_relative_to(root) or path in seen:
                continue
            seen.add(path)
            files.append({"path": str(path), "relative": str(path.relative_to(root))})
        if not recursive:
            break
    files.sort(key=lambda item: item["relative"].casefold())
    return str(root), files, warnings


def prepare_settings(values, presets):
    settings = dict(values)
    settings.setdefault("character_reference", False)
    settings.setdefault("gender_neutral", False)
    preset = next((p for p in presets if p["id"] == settings["preset"]), None)
    if preset is None:
        raise ValueError("Choose a description preset.")
    model = Path(settings["model_path"]).expanduser().resolve()
    if not model.is_file() or model.suffix.lower() != ".safetensors":
        raise ValueError("Choose an existing .safetensors vision model.")
    for field in ("prompt", "system_prompt"):
        settings[field] = settings[field].strip()
    if not settings["prompt"]:
        raise ValueError("Add instructions describing what the model should look for.")
    label = settings["output_label"].strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", label):
        raise ValueError("The output label needs 1–41 letters, digits, hyphens or underscores.")
    pose = next(p for p in presets if p["id"] == "pose")
    canonical = (settings["preset"] == "pose" and settings["prompt"] == pose["prompt"]
                 and settings["system_prompt"] == pose["system_prompt"]
                 and settings["max_tokens"] == pose["max_tokens"]
                 and not settings["character_reference"] and not settings["gender_neutral"])
    if label == "pose" and not canonical:
        label = "pose-custom"
    settings["output_label"] = label
    settings["legacy_pose_cache"] = canonical and label == "pose"
    settings["model_path"] = str(model)
    settings["model"] = model.name
    settings["profile_name"] = preset["name"]
    settings["prompt_hash"] = hashlib.sha256(
        (settings["system_prompt"] + "\n" + settings["prompt"]).encode()).hexdigest()
    stat = model.stat()
    settings["model_signature"] = digest_json([str(model), stat.st_size, stat.st_mtime_ns])
    settings["generation_hash"] = digest_json({
        "prompt": settings["prompt_hash"], "model_path": str(model),
        "model_bytes": stat.st_size, "model_modified_ns": stat.st_mtime_ns,
        "max_tokens": settings["max_tokens"], "sampling": "greedy", "thinking": False})
    if settings["output_directory"].strip():
        destination = Path(settings["output_directory"]).expanduser()
        if not destination.is_absolute():
            raise ValueError("Use an absolute output folder path, or leave it empty.")
        settings["output_directory"] = str(destination.resolve())
    else:
        settings["output_directory"] = ""
    return settings


def output_paths(item, settings):
    source = Path(item["path"])
    if settings["output_directory"]:
        root = Path(settings["output_directory"]).resolve()
        relative = Path(item["relative"])
        base = (root / relative).resolve()
        if not base.is_relative_to(root):
            raise ValueError("The output path leaves the selected output folder.")
    else:
        base = source
    suffix = "." + settings["output_label"]
    return base.with_name(base.name + suffix + ".json"), base.with_name(base.name + suffix + ".txt")


def read_cache(path, image_hash, settings):
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(record, dict):
        return None
    # Keep the original model text so output guidance can change without inference.
    # Older records contain only the unmodified caption.
    if "raw_caption" in record or record.get("character_reference") or record.get("gender_neutral"):
        if not isinstance(record.get("raw_caption"), str) or not record["raw_caption"].strip():
            return None
    if (record.get("schema_version") != 1 or record.get("image_sha256") != image_hash
            or record.get("model") != settings["model"]
            or record.get("caption_prompt_sha256") != settings["prompt_hash"]
            or not isinstance(record.get("caption"), str) or not record["caption"].strip()):
        return None
    generation = record.get("generation_hash")
    if generation != settings["generation_hash"]:
        if generation is not None or not settings["legacy_pose_cache"]:
            return None
    return record


def format_caption(caption, settings):
    if settings.get("character_reference", False):
        caption = caption.rstrip() + "\n\n" + CHARACTER_REFERENCE_GUIDANCE
    return neutralize_gender(caption) if settings.get("gender_neutral", False) else caption


def save_description(item, settings, image_hash, caption):
    json_path, text_path = output_paths(item, settings)
    record = {"schema_version": 1, "image_filename": Path(item["path"]).name,
              "image_sha256": image_hash, "model": settings["model"],
              "caption_prompt_sha256": settings["prompt_hash"], "caption": format_caption(caption, settings),
              "raw_caption": caption, "character_reference": settings.get("character_reference", False),
              "gender_neutral": settings.get("gender_neutral", False),
              "created_at": now(), "profile": settings["preset"],
              "generation_hash": settings["generation_hash"],
              "instructions": settings["prompt"], "system_prompt": settings["system_prompt"],
              "max_tokens": settings["max_tokens"]}
    atomic_text(json_path, json.dumps(record, ensure_ascii=False, indent=2))
    if settings["write_txt"]:
        atomic_text(text_path, record["caption"] + "\n")
    return json_path, text_path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, settings TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, position INTEGER NOT NULL,
                    path TEXT NOT NULL, relative TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    caption TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    source_sha256 TEXT NOT NULL DEFAULT '', output_json TEXT NOT NULL DEFAULT '',
                    output_txt TEXT NOT NULL DEFAULT '', seconds REAL NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS item_job ON items(job_id, position);
            """)
            db.execute("UPDATE jobs SET status='paused',error=? WHERE status IN ('running','queued','pausing','cancelling')",
                       ("The app restarted. Resume to continue from the saved results.",))
            db.execute("UPDATE items SET status='pending' WHERE status='running'")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, settings, files):
        job_id = uuid.uuid4().hex
        timestamp = now()
        with self.db() as db:
            db.execute("INSERT INTO jobs(id,status,settings,created_at,updated_at) VALUES (?,?,?,?,?)",
                       (job_id, "queued", json.dumps(settings), timestamp, timestamp))
            db.executemany("INSERT INTO items(job_id,position,path,relative) VALUES (?,?,?,?)",
                [(job_id, i, item["path"], item["relative"]) for i, item in enumerate(files)])
        return job_id

    def job(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            counts = db.execute("SELECT status,COUNT(*) AS n FROM items WHERE job_id=? GROUP BY status", (job_id,)).fetchall()
            average = db.execute("SELECT AVG(seconds) FROM items WHERE job_id=? AND status='done'", (job_id,)).fetchone()[0]
            current = db.execute("SELECT relative FROM items WHERE job_id=? AND status='running' LIMIT 1", (job_id,)).fetchone()
        result["settings"] = json.loads(result["settings"])
        result["counts"] = {r["status"]: r["n"] for r in counts}
        result["total"] = sum(result["counts"].values())
        result["processed"] = sum(result["counts"].get(k, 0) for k in ("done", "cached", "failed"))
        result["current_file"] = current["relative"] if current else ""
        result["eta_seconds"] = round((result["total"] - result["processed"]) * average) if average else None
        return result

    def jobs(self):
        with self.db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM jobs ORDER BY created_at DESC LIMIT 100")]
        return [self.job(job_id) for job_id in ids]

    def next_job(self):
        with self.db() as db:
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',started_at=COALESCE(started_at,?),updated_at=?,error='' WHERE id=?",
                           (now(), now(), row[0]))
        return row[0] if row else None

    def update_job(self, job_id, **fields):
        fields["updated_at"] = now()
        with self.db() as db:
            db.execute("UPDATE jobs SET " + ",".join(key + "=?" for key in fields) + " WHERE id=?",
                       [*fields.values(), job_id])

    def items(self, job_id, offset=0, limit=24):
        with self.db() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM items WHERE job_id=? ORDER BY position LIMIT ? OFFSET ?", (job_id, limit, offset))]

    def item(self, item_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def next_item(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM items WHERE job_id=? AND status='pending' ORDER BY position LIMIT 1", (job_id,)).fetchone()
        return dict(row) if row else None

    def update_item(self, item_id, **fields):
        with self.db() as db:
            db.execute("UPDATE items SET " + ",".join(key + "=?" for key in fields) + " WHERE id=?",
                       [*fields.values(), item_id])

    def resume(self, job_id):
        with self.db() as db:
            db.execute("UPDATE items SET status='pending',error='' WHERE job_id=? AND status IN ('failed','running')", (job_id,))
            db.execute("UPDATE jobs SET status='queued',error='',finished_at=NULL,updated_at=? WHERE id=?", (now(), job_id))
