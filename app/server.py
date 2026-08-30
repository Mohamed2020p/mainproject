"""
IL2CPP Dumper Studio - web front end.

Runs anywhere Flask does:

    python3 app/server.py                     # local / sandbox
    %run colab/IL2CPP_Dumper_Studio.ipynb      # Google Colab

The UI is a thin client over a small JSON API.  A dump runs in a worker thread;
the browser polls ``/api/status/<job_id>`` for progress, logs and results, so it
works identically behind the Google Colab reverse proxy, in this sandbox's live
preview, or on ``localhost``.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import traceback
import uuid
import zipfile
from typing import Any, Dict, List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from flask import (Flask, Response, jsonify, render_template, request,
                   send_file, send_from_directory)

from dumper.apk import ApkError, list_abis, looks_like_archive
from dumper.binary import BinaryError
from dumper.lib_only import dump_lib_only, extract_lib
from dumper.pipeline import DumpOptions, dump_apk, dump_bytes, dump_files

APP = Flask(__name__, template_folder="templates", static_folder="static")
APP.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024   # 1 GiB

STATE_LOCK = threading.Lock()
JOBS: Dict[str, Dict[str, Any]] = {}
UPLOAD_DIR = os.path.join(REPO_ROOT, ".uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

PORT = int(os.environ.get("PORT", "8050"))


def _purge_stale_uploads(max_age_seconds: int = 3600) -> None:
    """Delete leftover uploads / zip caches older than an hour so repeated
    dumps do not keep growing the working directory."""
    now = time.time()
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        try:
            if now - os.path.getmtime(path) > max_age_seconds:
                os.remove(path)
        except OSError:
            pass


_purge_stale_uploads()


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------
@APP.route("/")
def index() -> Response:
    return render_template("index.html")


@APP.route("/favicon.ico")
def favicon() -> Response:
    return send_from_directory(APP.static_folder, "img/favicon.ico",
                               mimetype="image/x-icon")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@APP.route("/api/health")
def health() -> Response:
    from dumper import __version__
    return jsonify({"ok": True, "version": __version__,
                    "developer": "Mohamed Annati"})


@APP.route("/api/apk/abis", methods=["POST"])
def apk_abis() -> Response:
    """Probe an uploaded APK and report the ABIs it ships."""
    payload = request.get_json(silent=True) or {}
    path = payload.get("path")
    if not path or not os.path.isfile(path):
        return jsonify({"ok": False, "error": "No APK uploaded."}), 400
    try:
        abis = list_abis(path)
        return jsonify({"ok": True, "abis": abis})
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 400


@APP.route("/api/upload", methods=["POST"])
def upload() -> Response:
    files = list(request.files.values())
    if not files:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400
    stored = []
    for item in files:
        safe = os.path.basename(item.filename or "file.bin").replace("\x00", "")
        dest = os.path.join(UPLOAD_DIR, "%s_%s" % (uuid.uuid4().hex[:8], safe))
        item.save(dest)
        stored.append({"name": safe, "path": dest, "size": os.path.getsize(dest)})
    return jsonify({"ok": True, "files": stored})


@APP.route("/api/dump", methods=["POST"])
def start_dump() -> Response:
    payload = request.get_json(silent=True) or {}
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "status": "queued", "progress": 0.0, "logs": [],
           "result": None, "error": None, "started": time.time()}
    with STATE_LOCK:
        JOBS[job_id] = job
    thread = threading.Thread(target=_run_job, args=(job_id, payload), daemon=True)
    thread.start()
    return jsonify({"ok": True, "jobId": job_id})


def _progress(job: Dict[str, Any]):
    def emit(fraction: float, message: str) -> None:
        job["progress"] = round(min(1.0, max(0.0, fraction)), 3)
        line = message.strip()
        if line:
            job["logs"].append(line)
    return emit


def _run_lib_only(archive, binary, options, payload, job):
    """Metadata-free analysis: accepts an APK or a bare libil2cpp.so."""
    raw = payload.get("il2cppVersion")
    version = None
    try:
        if raw not in (None, "", "auto"):
            version = float(raw)
    except (TypeError, ValueError):
        version = None
    if archive:
        data, _entry, abi, available = extract_lib(archive, options.preferred_abi)
        job["logs"].append("ABI selected     : %s (available: %s)"
                           % (abi, ", ".join(available)))
    elif binary:
        with open(binary, "rb") as handle:
            head = handle.read(8)
            handle.seek(0)
            if looks_like_archive(head):       # an APK was dropped in lib mode
                data, _entry, abi, available = extract_lib(binary,
                                                           options.preferred_abi)
                job["logs"].append("ABI selected     : %s (available: %s)"
                                   % (abi, ", ".join(available)))
            else:
                data = handle.read()
    else:
        raise ValueError("Lib-only mode needs an APK or a libil2cpp.so.")
    return dump_lib_only(data, options, version, _progress(job))


def _run_job(job_id: str, payload: Dict[str, Any]) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    options = DumpOptions.from_dict(payload)
    try:
        archive = payload.get("apkPath")
        binary = payload.get("binaryPath")
        metadata = payload.get("metadataPath")

        if payload.get("libOnly"):
            result = _run_lib_only(archive, binary, options, payload, job)
        elif archive:
            result = dump_apk(archive, options, _progress(job))
        elif binary and metadata:
            result = dump_files(binary, metadata, options, _progress(job))
        elif metadata:
            result = dump_files("", metadata, options, _progress(job))
        else:
            raise ValueError("Upload an APK, or a libil2cpp.so + "
                             "global-metadata.dat pair first.")

        job["result"] = result.summary()
        job["status"] = "done" if result.ok else "error"
        job["error"] = result.error
        job["progress"] = 1.0
    except (ApkError, BinaryError, ValueError) as error:
        job["status"] = "error"
        job["error"] = str(error)
    except Exception as error:                       # pragma: no cover
        job["status"] = "error"
        job["error"] = "%s\n%s" % (error, traceback.format_exc(limit=3))
        job["logs"].append(traceback.format_exc(limit=4))


@APP.route("/api/status/<job_id>")
def status(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "Unknown job."}), 404
    with STATE_LOCK:
        logs_tail = list(job["logs"][-400:])
        snapshot = {
            "ok": True,
            "status": job["status"],
            "progress": job["progress"],
            "logs": logs_tail,
            # Absolute position of the tail so the client can diff even once the
            # buffer wraps past 400 lines (it was dropping lines before).
            "logStart": len(job["logs"]) - len(logs_tail),
            "logCount": len(job["logs"]),
            "result": job["result"],
            "error": job["error"],
        }
    return jsonify(snapshot)


@APP.route("/api/preview/<job_id>")
def preview(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job or not job["result"]:
        return jsonify({"ok": False, "error": "No result."}), 404
    path = _find_result_file(job["result"], "dump.cs")
    if path is None or not os.path.isfile(path):
        return jsonify({"ok": False, "error": "dump.cs missing."}), 404
    query = request.args.get("q", "")
    limit = int(request.args.get("max", "1200"))
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read(4_000_000)
    if query:
        lines = content.split("\n")
        kept = [line for line in lines if query.lower() in line.lower()]
        content = "\n".join(kept[:limit])
    else:
        content = content[: limit * 80]
    return jsonify({"ok": True, "content": content,
                    "truncated": True, "query": query})


@APP.route("/api/download/<job_id>/<name>")
def download(job_id: str, name: str) -> Response:
    job = JOBS.get(job_id)
    if not job or not job["result"]:
        return jsonify({"ok": False, "error": "No result."}), 404
    if name == "all.zip":
        return _zip_result(job)
    path = _find_result_file(job["result"], name)
    if path is None:
        return jsonify({"ok": False, "error": "File not found."}), 404
    if os.path.isdir(path):
        return _zip_folder(path, os.path.basename(path) + ".zip")
    return send_file(path, as_attachment=True)


def _find_result_file(result: Dict[str, Any], name: str) -> Optional[str]:
    for item in result.get("files", []):
        if item.get("name") == name:
            return item.get("path")
    return None


def _zip_result(job: Dict[str, Any]) -> Response:
    out_dir = job["result"]["outputDir"]
    archive_path = os.path.join(UPLOAD_DIR, job["id"] + "_all.zip")
    if not os.path.exists(archive_path):
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for root, _dirs, files in os.walk(out_dir):
                for file in files:
                    full = os.path.join(root, file)
                    archive.write(full, os.path.relpath(full, out_dir))
    return send_file(archive_path, as_attachment=True,
                     download_name="il2cpp-dump.zip")


def _zip_folder(folder: str, archive_name: str) -> Response:
    archive_path = os.path.join(UPLOAD_DIR, uuid.uuid4().hex[:8] + ".zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(folder):
            for file in files:
                full = os.path.join(root, file)
                archive.write(full, os.path.join(
                    os.path.basename(folder), os.path.relpath(full, folder)))
    return send_file(archive_path, as_attachment=True, download_name=archive_name)


@APP.route("/api/cleanup", methods=["POST"])
def cleanup() -> Response:
    payload = request.get_json(silent=True) or {}
    path = payload.get("path")
    if path and path.startswith(UPLOAD_DIR):
        try:
            os.remove(path)
        except OSError:
            pass
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
def _detect_colab_proxy(port: int) -> Optional[str]:
    try:
        from google.colab.output import eval_js  # noqa: F401
        from google.colab import output
        return output.eval_js("google.colab.kernel.proxyPort(%d)" % port)
    except Exception:
        return None


def main() -> None:
    proxy = _detect_colab_proxy(PORT)
    print("=" * 64)
    print("  IL2CPP Dumper Studio  -  developed by Mohamed Annati")
    if proxy:
        print("  Google Colab URL: %s" % proxy)
    print("  Listening on 0.0.0.0:%d" % PORT)
    print("=" * 64)
    APP.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
