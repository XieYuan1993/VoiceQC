"""Dyna file upload -> asynchronous ASR -> checkpointed Flow correction."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import uuid
import wave
from pathlib import Path

import httpx
from google.api_core.exceptions import NotFound
from voiceqa_shared import gcs

from worker.asr.base import FileResult, SegmentResult
from worker.settings import settings

MODELS = {"manual_split_16k_yue", "manual_split_16k"}
LINE = re.compile(r"^([12])\|(\d+):(\d+\.\d+)\s*-\s*(\d+):(\d+\.\d+)\|(.*)$")


def chunks(audio):
    result, current, size = [], [], 0
    for segment in audio:
        line = f"user{int(segment['speakerId']) + 1} ({segment['startTime'] / 1000:.2f} {segment['endTime'] / 1000:.2f}):{segment['text']}"
        if len(line) > 12000:
            raise RuntimeError("Dyna ASR segment exceeds Flow input limit")
        if current and (len(current) >= 120 or size + len(line) + 1 > 12000):
            result.append(current)
            current, size = [], 0
        current.append((segment, line))
        size += len(line) + 1
    if current:
        result.append(current)
    return result


def corrected_segments(text, source):
    parsed = [LINE.fullmatch(line.strip()) for line in text.splitlines() if line.strip()]
    if len(parsed) != len(source) or not all(parsed):
        raise RuntimeError("Dyna Flow line count/format mismatch; original transcript retained")
    result = []
    for match, (segment, _) in zip(parsed, source, strict=True):
        start = round((int(match[2]) * 60 + float(match[3])) * 1000)
        end = round((int(match[4]) * 60 + float(match[5])) * 1000)
        if (
            abs(start - segment["startTime"]) > 10
            or abs(end - segment["endTime"]) > 10
            or not match[6].strip()
        ):
            raise RuntimeError("Dyna Flow changed segment timings or returned empty text")
        # Role comes from the source audio channel, NEVER the LLM's 1/2 labels.
        result.append(
            {
                "speakerId": int(segment["speakerId"]),
                "startTime": start,
                "endTime": end,
                "text": match[6].strip(),
            }
        )
    return result


class DynaASR:
    provider = "dyna"

    def __init__(
        self, source_uri=None, broker_channel="left", checkpoint_prefix="stt-results/dyna"
    ):
        self.source_uri = source_uri
        self.broker_channel = broker_channel
        self.checkpoint_prefix = checkpoint_prefix

    def _request(self, method, path, **kwargs):
        required = {
            "robot key": settings.DYNA_ROBOT_KEY.get_secret_value(),
            "robot token": settings.DYNA_ROBOT_TOKEN.get_secret_value(),
            "JWT": settings.DYNA_JWT.get_secret_value(),
            "tenant": settings.DYNA_TENANT,
            "username": settings.DYNA_USERNAME,
            "flow": settings.DYNA_FLOW_UUID,
        }
        if not all(required.values()) or not settings.DYNA_ROBOT_ID:
            raise RuntimeError("Dyna ASR environment is incomplete; configure DYNA_* on STT worker")
        headers = {
            "cybertron-robot-key": required["robot key"],
            "cybertron-robot-token": required["robot token"],
            "Authorization": "Bearer " + required["JWT"],
            "X-Tenant-Name": required["tenant"],
        }
        try:
            response = httpx.request(
                method,
                settings.DYNA_BASE_URL.rstrip("/") + path,
                headers=headers,
                timeout=httpx.Timeout(200, connect=20),
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "Dyna request timed out; retry will resume saved task/chunks"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Dyna connection aborted; retry will resume saved task/chunks"
            ) from exc
        if response.status_code in (401, 403):
            raise RuntimeError(
                "Dyna authentication failed; refresh DYNA_JWT and verify robot credentials"
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise RuntimeError(f"Dyna UNAVAILABLE HTTP {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"Dyna HTTP {response.status_code}")
        payload = response.json()
        if str(payload.get("code")) != "000000":
            # Never echo a provider error body which may contain authentication/input.
            raise RuntimeError(
                "Dyna API rejected request (code " + str(payload.get("code"))[:20] + ")"
            )
        return payload["data"]

    def _read(self, key):
        try:
            return json.loads(gcs.read_uri_bytes(gcs.to_uri(key)))
        except NotFound:
            return None

    def _save(self, key, value):
        gcs.upload_fileobj(
            key, io.BytesIO(json.dumps(value, ensure_ascii=False).encode()), "application/json"
        )

    def start_batch(
        self, files, *, language_mode, adaptation_phrases, model, output_prefix_uri=None
    ):
        if not self.source_uri or {file.channel_role for file in files} != {"broker", "customer"}:
            raise RuntimeError(
                "Dyna ASR currently requires original stereo WAV and two separated role channels"
            )
        engine = (
            model
            if model in MODELS
            else ("manual_split_16k" if language_mode == "cmn-Hans-CN" else settings.DYNA_ASR_MODEL)
        )
        if engine not in MODELS:
            raise RuntimeError("Unsupported Dyna ASR engine")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recording.wav"
            gcs.download_uri_to_file(self.source_uri, str(path))
            try:
                with wave.open(str(path)) as audio:
                    if audio.getnchannels() != 2:
                        raise RuntimeError("Dyna ASR requires a two-channel WAV")
                    duration = audio.getnframes() / audio.getframerate()
            except (wave.Error, EOFError) as exc:
                raise RuntimeError(
                    "Dyna ASR currently supports original stereo PCM WAV only"
                ) from exc
            digest = hashlib.md5()
            with path.open("rb") as source:
                short_hash = hashlib.md5(source.read(262144)).hexdigest()
                source.seek(0)
                while block := source.read(1024 * 1024):
                    digest.update(block)
            uploaded = self._request(
                "POST",
                "/openapi/v1/file/batch/init",
                json={
                    "files": [
                        {
                            "file_name": "recording.wav",
                            "file_short_hash": short_hash,
                            "file_hash": digest.hexdigest(),
                            "file_size": path.stat().st_size,
                            "mime_type": "audio/x-wav",
                        }
                    ]
                },
            )[0]
            if uploaded["file_status"] != "uploaded":
                parts = uploaded.get("parts") or []
                if not parts:
                    raise RuntimeError("Dyna upload returned no pending chunks")
                with path.open("rb") as source:
                    for part in parts:
                        offset, size = int(part["offset"]), int(part["size"])
                        if (
                            offset < 0
                            or size <= 0
                            or size > 16 * 1024 * 1024
                            or offset + size > path.stat().st_size
                        ):
                            raise RuntimeError("Invalid Dyna upload chunk bounds")
                        source.seek(offset)
                        block = source.read(size)
                        self._request(
                            "POST",
                            "/openapi/v1/file/batch/part",
                            data={
                                "file_uuid": uploaded["file_uuid"],
                                "part_number": str(part["part_number"]),
                                "part_hash": hashlib.md5(block).hexdigest(),
                            },
                            files={"part_data": ("part.bin", block, "application/octet-stream")},
                        )
                self._request(
                    "POST",
                    "/openapi/v1/file/batch/complete",
                    json={"file_uuid": uploaded["file_uuid"]},
                )
        task = self._request(
            "POST",
            "/api/file_parse_public/v1/async/task",
            json={
                "request_id": uuid.uuid4().hex,
                "model_value": engine,
                "parse_prompt": "",
                "resource_type": "file_uuid",
                "resources": [{"file_uuid": uploaded["file_uuid"]}],
                "auth": {
                    "robot_key": settings.DYNA_ROBOT_KEY.get_secret_value(),
                    "robot_token": settings.DYNA_ROBOT_TOKEN.get_secret_value(),
                },
                "run_time_args": {"with_time": True},
            },
        )
        return json.dumps(
            {
                "provider": "dyna",
                "task": task["task_uuid"],
                "engine": engine,
                "files": {file.channel_role: file.uri for file in files},
                "broker_channel": self.broker_channel,
                "duration": duration,
                "prefix": self.checkpoint_prefix,
                "flow": settings.DYNA_FLOW_UUID,
                "robot_id": settings.DYNA_ROBOT_ID,
            }
        )

    def fetch_result(self, operation_name):
        operation = json.loads(operation_name)
        prefix = operation["prefix"] + "/" + operation["task"]
        audio = self._read(prefix + "/raw.json")
        if audio is None:
            state = self._request(
                "GET",
                "/api/file_parse_public/v1/async/task/status",
                params={"task_uuid": operation["task"]},
            )["status"]
            if state in ("FAILED", "TIMEOUT"):
                raise RuntimeError("Dyna ASR terminal status " + state)
            if state != "SUCCEEDED":
                return None
            audio = self._request(
                "GET",
                "/api/file_parse_public/v1/async/task/detail",
                params={"task_uuid": operation["task"]},
            )["result"]["audio"]
            if not audio or any(int(item["speakerId"]) not in (0, 1) for item in audio):
                raise RuntimeError("Dyna returned empty or invalid stereo segments")
            audio = sorted(audio, key=lambda item: item["startTime"])
            self._save(prefix + "/raw.json", audio)
        corrected = []
        groups = chunks(audio)
        for index, group in enumerate(groups):
            key = prefix + f"/flow-{index}.json"
            result = self._read(key)
            if result is None:
                body = {
                    "task": {
                        "id": index + 1,
                        "name": "voiceqa-asr",
                        "type": 1,
                        "payload": {
                            "action": "exec_workflow",
                            "params": {
                                "flow_uuid": operation["flow"],
                                "robot_id": operation["robot_id"],
                                "message_source": "openapi-ws",
                                "username": settings.DYNA_USERNAME,
                                "session_id": str(uuid.uuid4()),
                                "node_inputs": {
                                    "UploadFile": "File1:recording.wav:\nContent1\n"
                                    + "\n".join(line for _, line in group)
                                    + "\n"
                                },
                            },
                        },
                    }
                }
                response = self._request(
                    "POST", "/chat/api/v1/workflow/run/offline-task?sync=1", json=body
                )["result"]
                if response["status"] != 1:
                    raise RuntimeError(
                        "Dyna Flow failed; check workflow deployment and credentials"
                    )
                result = corrected_segments(response["result"], group)
                self._save(key, result)
                if index + 1 < len(groups):
                    # Yield after each remote chunk so the pipeline refreshes its
                    # heartbeat and releases the worker between long-call chunks.
                    return None
            corrected.extend(result)
        broker_id = 0 if operation["broker_channel"] == "left" else 1
        results = []
        for role, uri in operation["files"].items():
            speaker = broker_id if role == "broker" else 1 - broker_id
            segments = [
                SegmentResult(
                    start_ms=item["startTime"],
                    end_ms=item["endTime"],
                    text=item["text"],
                    language="zh-Hant",
                )
                for item in corrected
                if item["speakerId"] == speaker
            ]
            results.append(
                FileResult(
                    uri=uri,
                    segments=segments,
                    language_detected="zh-Hant",
                    billed_seconds=operation["duration"] / 2,
                )
            )
        return results
