from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from debate_agent import (
    DebateRunner,
    SpeechResult,
    default_model,
    provider_is_ready,
)


PROJECT_DIR = Path(__file__).resolve().parent


def load_env_file() -> None:
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env_file()

DATA_DIR = Path(
    os.environ.get("AI_DEBATE_DATA_DIR", PROJECT_DIR / "data" / "debates")
).resolve()
RECORD_ID_PATTERN = re.compile(r"^debate_[0-9]{8}T[0-9]{6}Z_[a-f0-9]{8}$")
INVALID_FOLDER_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WRITE_LOCK = threading.RLock()
JOB_LOCK = threading.Lock()
ACTIVE_JOBS: dict[
    str, tuple[threading.Thread, threading.Event, threading.Event]
] = {}
INSTANCE_LOCK_HANDLE = None


def acquire_instance_lock() -> bool:
    global INSTANCE_LOCK_HANDLE
    lock_path = PROJECT_DIR / ".server.lock"
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False

    INSTANCE_LOCK_HANDLE = handle
    return True


def release_instance_lock() -> None:
    global INSTANCE_LOCK_HANDLE
    handle = INSTANCE_LOCK_HANDLE
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
        INSTANCE_LOCK_HANDLE = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def create_record_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"debate_{timestamp}_{uuid.uuid4().hex[:8]}"


def safe_topic_folder_name(topic: str, record_id: str) -> str:
    cleaned_topic = INVALID_FOLDER_CHARACTERS.sub("_", topic)
    cleaned_topic = re.sub(r"\s+", " ", cleaned_topic).strip(" .")
    if not cleaned_topic:
        cleaned_topic = "未命名辩题"
    return f"{cleaned_topic[:60]}__{record_id}"


def record_path(record_id: str) -> Path:
    if not RECORD_ID_PATTERN.fullmatch(record_id):
        raise ValueError("无效的辩论记录 ID")

    legacy_path = DATA_DIR / f"{record_id}.json"
    if legacy_path.exists():
        return legacy_path

    nested_paths = list(DATA_DIR.glob(f"*__{record_id}/debate.json"))
    if nested_paths:
        return nested_paths[0]

    return DATA_DIR / f"__missing__{record_id}" / "debate.json"


def read_record(record_id: str) -> dict:
    path = record_path(record_id)
    with WRITE_LOCK:
        if not path.exists():
            raise FileNotFoundError(record_id)
        return json.loads(path.read_text(encoding="utf-8"))


def write_record(record: dict) -> None:
    with WRITE_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        legacy_path = DATA_DIR / f"{record['id']}.json"
        folder_name = record.get("storageFolder")
        if legacy_path.exists() and not folder_name:
            path = legacy_path
        else:
            if not isinstance(folder_name, str) or not folder_name.endswith(record["id"]):
                folder_name = safe_topic_folder_name(record["topic"], record["id"])
                record["storageFolder"] = folder_name
            folder = (DATA_DIR / folder_name).resolve()
            if folder.parent != DATA_DIR:
                raise ValueError("无效的记录目录")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "debate.json"
            record["storageFile"] = f"{folder_name}/debate.json"
        temporary_path = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            for attempt in range(6):
                try:
                    os.replace(temporary_path, path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.025 * (2**attempt))
        finally:
            temporary_path.unlink(missing_ok=True)


def mark_turn(record_id: str, round_number: int, side: str) -> None:
    with WRITE_LOCK:
        record = read_record(record_id)
        if record.get("status") != "running":
            return
        record["currentRound"] = round_number
        record["currentSpeaker"] = side
        record["updatedAt"] = utc_now()
        write_record(record)


def save_generated_speech(
    record_id: str,
    round_number: int,
    side: str,
    result: SpeechResult,
) -> None:
    with WRITE_LOCK:
        record = read_record(record_id)
        if record.get("status") != "running":
            return
        seat = record[side]
        created_at = utc_now()
        speech = {
            "id": f"speech_{uuid.uuid4().hex[:12]}",
            "sequence": len(record["speeches"]) + 1,
            "round": round_number,
            "side": side,
            "provider": seat["provider"],
            "model": seat["model"],
            "content": result.content,
            "status": result.status,
            "createdAt": created_at,
        }
        record["speeches"].append(speech)
        record["currentRound"] = round_number
        record["updatedAt"] = created_at
        write_record(record)


def mark_debate_error(record_id: str, message: str) -> None:
    with WRITE_LOCK:
        try:
            record = read_record(record_id)
        except FileNotFoundError:
            return
        if record.get("status") != "running":
            return
        record["status"] = "error"
        record["error"] = message
        record["currentSpeaker"] = None
        record["updatedAt"] = utc_now()
        record["finishedAt"] = record["updatedAt"]
        write_record(record)


def mark_debate_stopped(record_id: str) -> None:
    with WRITE_LOCK:
        try:
            record = read_record(record_id)
        except FileNotFoundError:
            return
        if record.get("status") not in {"running", "paused"}:
            return
        record["status"] = "stopped"
        record["currentSpeaker"] = None
        record["updatedAt"] = utc_now()
        record["finishedAt"] = record["updatedAt"]
        write_record(record)


def mark_debate_paused(record_id: str) -> None:
    with WRITE_LOCK:
        try:
            record = read_record(record_id)
        except FileNotFoundError:
            return
        if record.get("status") == "paused":
            return
        if record.get("status") != "running":
            return
        record["status"] = "paused"
        record["pauseRequested"] = False
        record["currentSpeaker"] = None
        record["updatedAt"] = utc_now()
        write_record(record)


def start_debate_job(record_id: str) -> None:
    stop_event = threading.Event()
    pause_event = threading.Event()
    runner = DebateRunner(
        record_id=record_id,
        stop_event=stop_event,
        pause_event=pause_event,
        load_record=read_record,
        mark_turn=mark_turn,
        save_speech=save_generated_speech,
        mark_paused=mark_debate_paused,
        mark_error=mark_debate_error,
        mark_stopped=mark_debate_stopped,
    )

    def run_and_cleanup() -> None:
        try:
            runner.run()
        finally:
            with JOB_LOCK:
                ACTIVE_JOBS.pop(record_id, None)

    thread = threading.Thread(
        target=run_and_cleanup,
        name=f"debate-{record_id}",
        daemon=True,
    )
    with JOB_LOCK:
        ACTIVE_JOBS[record_id] = (thread, stop_event, pause_event)
    thread.start()


def stop_debate_job(record_id: str) -> None:
    with JOB_LOCK:
        job = ACTIVE_JOBS.get(record_id)
    if job:
        job[1].set()


def pause_debate_job(record_id: str) -> bool:
    with JOB_LOCK:
        job = ACTIVE_JOBS.get(record_id)
    if not job:
        return False
    job[2].set()
    return True


def resume_debate_job(record_id: str) -> bool:
    with JOB_LOCK:
        job = ACTIVE_JOBS.get(record_id)
    if not job:
        return False
    job[2].clear()
    return True


def stop_all_jobs() -> None:
    with JOB_LOCK:
        jobs = list(ACTIVE_JOBS.values())
    for _, stop_event, _ in jobs:
        stop_event.set()


class DebateRequestHandler(SimpleHTTPRequestHandler):
    server_version = "AIDebateServer/1.0"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status: HTTPStatus, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("无效的请求长度") from error

        if content_length <= 0 or content_length > 1_000_000:
            raise ValueError("请求内容为空或过大")

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("请求内容不是有效 JSON") from error

        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return payload

    def api_path_parts(self) -> list[str]:
        path = unquote(urlparse(self.path).path)
        return [part for part in path.split("/") if part]

    def do_GET(self) -> None:
        parts = self.api_path_parts()

        if parts == ["api", "health"]:
            with JOB_LOCK:
                active_count = len(ACTIVE_JOBS)
            self.send_json(
                HTTPStatus.OK,
                {"status": "ok", "activeDebates": active_count},
            )
            return

        if parts == ["api", "config"]:
            self.send_json(
                HTTPStatus.OK,
                {
                    "providers": {
                        provider: {
                            "ready": provider_is_ready(provider),
                            "model": default_model(provider),
                        }
                        for provider in ("kimi", "deepseek")
                    }
                },
            )
            return

        if parts == ["api", "debates"]:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            records = []
            record_files = list(DATA_DIR.glob("*/debate.json"))
            record_files.extend(DATA_DIR.glob("debate_*.json"))
            for path in sorted(record_files, reverse=True):
                try:
                    with WRITE_LOCK:
                        record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                records.append(
                    {
                        "id": record.get("id"),
                        "topic": record.get("topic"),
                        "status": record.get("status"),
                        "affirmative": record.get("affirmative"),
                        "negative": record.get("negative"),
                        "createdAt": record.get("createdAt"),
                        "updatedAt": record.get("updatedAt"),
                    }
                )
            records.sort(key=lambda record: record.get("createdAt") or "", reverse=True)
            self.send_json(HTTPStatus.OK, {"debates": records})
            return

        if len(parts) == 3 and parts[:2] == ["api", "debates"]:
            try:
                record = read_record(parts[2])
            except ValueError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            except FileNotFoundError:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "记录不存在"})
                return
            self.send_json(HTTPStatus.OK, {"debate": record})
            return

        super().do_GET()

    def do_POST(self) -> None:
        parts = self.api_path_parts()

        try:
            payload = self.read_json_body()
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return

        if parts == ["api", "debates"]:
            self.create_debate(payload)
            return

        if (
            len(parts) == 4
            and parts[:2] == ["api", "debates"]
            and parts[3] == "speeches"
        ):
            self.append_speech(parts[2], payload)
            return

        self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

    def do_PATCH(self) -> None:
        parts = self.api_path_parts()
        if len(parts) != 3 or parts[:2] != ["api", "debates"]:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            return

        try:
            payload = self.read_json_body()
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return

        status = payload.get("status")
        if status not in {"running", "paused", "stopped", "completed", "error"}:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "无效的辩论状态"})
            return

        record_id = parts[2]
        if status == "paused" and not pause_debate_job(record_id):
            self.send_json(HTTPStatus.CONFLICT, {"error": "辩论任务未在运行"})
            return

        if status in {"stopped", "completed", "error"}:
            stop_debate_job(record_id)

        try:
            with WRITE_LOCK:
                record = read_record(record_id)
                if status == "paused":
                    if record.get("status") not in {"running", "paused"}:
                        self.send_json(
                            HTTPStatus.CONFLICT,
                            {"error": "当前状态不能暂停"},
                        )
                        return
                    if record.get("status") == "running":
                        record["pauseRequested"] = True
                else:
                    record["status"] = status
                    record["pauseRequested"] = False
                if status in {"stopped", "completed", "error"}:
                    record["currentSpeaker"] = None
                record["updatedAt"] = utc_now()
                if status in {"stopped", "completed", "error"}:
                    record["finishedAt"] = record["updatedAt"]
                write_record(record)
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        except FileNotFoundError:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "记录不存在"})
            return

        if status == "running":
            resume_debate_job(record_id)

        self.send_json(HTTPStatus.OK, {"debate": record})

    def create_debate(self, payload: dict) -> None:
        topic = str(payload.get("topic", "")).strip()
        affirmative = payload.get("affirmative")
        negative = payload.get("negative")

        if not topic or len(topic) > 120:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "辩题长度必须为 1 至 120 字"})
            return
        if not self.valid_side(affirmative) or not self.valid_side(negative):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "辩手信息无效"})
            return

        affirmative = self.normalize_side(affirmative)
        negative = self.normalize_side(negative)
        missing_providers = sorted(
            {
                side["provider"]
                for side in (affirmative, negative)
                if not provider_is_ready(side["provider"])
            }
        )
        if missing_providers:
            names = "、".join(
                "Kimi" if provider == "kimi" else "DeepSeek"
                for provider in missing_providers
            )
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"请先在 .env 中配置 {names} API 密钥"},
            )
            return

        created_at = utc_now()
        record = {
            "schemaVersion": 1,
            "id": create_record_id(),
            "topic": topic,
            "status": "running",
            "affirmative": affirmative,
            "negative": negative,
            "currentRound": 1,
            "currentSpeaker": None,
            "pauseRequested": False,
            "createdAt": created_at,
            "updatedAt": created_at,
            "finishedAt": None,
            "speeches": [],
        }
        record["storageFolder"] = safe_topic_folder_name(topic, record["id"])

        with WRITE_LOCK:
            write_record(record)
        start_debate_job(record["id"])
        self.send_json(HTTPStatus.CREATED, {"debate": record})

    def append_speech(self, record_id: str, payload: dict) -> None:
        side = payload.get("side")
        content = str(payload.get("content", "")).strip()
        if side not in {"affirmative", "negative"} or not content:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "发言内容无效"})
            return

        try:
            with WRITE_LOCK:
                record = read_record(record_id)
                seat = record[side]
                speech = {
                    "id": f"speech_{uuid.uuid4().hex[:12]}",
                    "sequence": len(record["speeches"]) + 1,
                    "round": int(payload.get("round", record["currentRound"])),
                    "side": side,
                    "provider": seat["provider"],
                    "model": seat["model"],
                    "content": content,
                    "status": str(payload.get("status", "completed")),
                    "createdAt": utc_now(),
                }
                record["speeches"].append(speech)
                record["currentRound"] = max(record["currentRound"], speech["round"])
                record["updatedAt"] = speech["createdAt"]
                write_record(record)
        except (TypeError, ValueError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "发言参数无效"})
            return
        except FileNotFoundError:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "记录不存在"})
            return

        self.send_json(HTTPStatus.CREATED, {"speech": speech})

    @staticmethod
    def valid_side(side: object) -> bool:
        if not isinstance(side, dict):
            return False
        provider = side.get("provider")
        model = side.get("model")
        return provider in {"kimi", "deepseek"} and (
            model is None or (isinstance(model, str) and bool(model.strip()))
        )

    @staticmethod
    def normalize_side(side: dict) -> dict:
        provider = side["provider"]
        requested_model = str(side.get("model", "")).strip()
        return {
            "provider": provider,
            "model": requested_model or default_model(provider),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 AI 辩论场本地服务")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()

    os.chdir(PROJECT_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    address = ("127.0.0.1", 4173)
    url = f"http://{address[0]}:{address[1]}/"
    if not acquire_instance_lock():
        print(f"AI 辩论场已经在运行：{url}")
        if args.open:
            webbrowser.open(url)
        return

    server = None
    try:
        server = ThreadingHTTPServer(address, DebateRequestHandler)
    except Exception:
        release_instance_lock()
        raise

    print(f"AI 辩论场已启动：{url}")
    print(f"辩论记录保存位置：{DATA_DIR}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        stop_all_jobs()
        if server is not None:
            server.server_close()
        release_instance_lock()


if __name__ == "__main__":
    main()
