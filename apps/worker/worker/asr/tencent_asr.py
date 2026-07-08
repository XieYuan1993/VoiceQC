"""Tencent Cloud ASR recording-file adapter.

Uses CreateRecTask / DescribeTaskStatus with TC3-HMAC-SHA256 signing. The
Tencent "普方英大模型" engine is EngineModelType=16k_zh_en.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from loguru import logger
from voiceqa_shared import asr_audio_proxy, gcs

from worker.asr.base import AdaptationPhrase, ChannelFile, FileResult, SegmentResult
from worker.settings import settings

ENDPOINT = "asr.tencentcloudapi.com"
SERVICE = "asr"
VERSION = "2019-06-14"
URL_EXPIRES_SECONDS = 4 * 60 * 60


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _tc3_headers(action: str, payload: dict[str, Any]) -> dict[str, str]:
    secret_id = settings.TENCENT_SECRET_ID.get_secret_value()
    secret_key = settings.TENCENT_SECRET_KEY.get_secret_value()
    if not secret_id or not secret_key:
        raise RuntimeError(
            "Tencent ASR selected but TENCENT_SECRET_ID / TENCENT_SECRET_KEY are not set"
        )

    timestamp = int(time.time())
    date = datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    hashed_payload = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{ENDPOINT}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join(["POST", "/", "", canonical_headers, signed_headers, hashed_payload])
    credential_scope = f"{date}/{SERVICE}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, SERVICE)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": ENDPOINT,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": VERSION,
    }
    if settings.TENCENT_ASR_REGION:
        headers["X-TC-Region"] = settings.TENCENT_ASR_REGION
    return headers


def _post(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    resp = httpx.post(
        f"https://{ENDPOINT}/",
        headers=_tc3_headers(action, payload),
        content=payload_json.encode("utf-8"),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    response = data.get("Response") or {}
    if "Error" in response:
        err = response["Error"]
        raise RuntimeError(f"Tencent ASR {err.get('Code')}: {err.get('Message')}")
    return response


def _hotword_list(phrases: list[AdaptationPhrase]) -> str | None:
    items: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        value = phrase.value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        weight = min(11, max(1, round(phrase.boost or 5)))
        items.append(f"{value[:30]}|{weight}")
        if len(items) >= 128:
            break
    return ",".join(items) if items else None


def _parse_detail(detail: list[dict[str, Any]]) -> list[SegmentResult]:
    segments: list[SegmentResult] = []
    for item in detail:
        text = str(item.get("FinalSentence") or item.get("SliceSentence") or "").strip()
        if not text:
            continue
        words = [
            (
                int(w.get("OffsetStartMs") or 0),
                str(w.get("Word") or "").strip(),
            )
            for w in item.get("Words") or []
            if str(w.get("Word") or "").strip()
        ]
        segments.append(
            SegmentResult(
                start_ms=int(item.get("StartMs") or 0),
                end_ms=int(item.get("EndMs") or item.get("StartMs") or 0),
                text=text,
                language="zh-Hant",
                confidence=None,
                words=words or None,
            )
        )
    return segments


class TencentASR:
    provider = "tencent"

    def _audio_url(self, uri: str) -> str:
        if settings.ASR_AUDIO_PROXY_BASE_URL:
            return asr_audio_proxy.create_url(
                settings.ASR_AUDIO_PROXY_BASE_URL,
                uri,
                settings.INTERNAL_API_SECRET.get_secret_value(),
                expires_in_seconds=URL_EXPIRES_SECONDS,
            )
        url = gcs.signed_url(uri, minutes=URL_EXPIRES_SECONDS // 60)
        if not url:
            raise RuntimeError("cannot sign audio URL for Tencent ASR")
        return url

    def start_batch(
        self,
        files: list[ChannelFile],
        *,
        language_mode: str,
        adaptation_phrases: list[AdaptationPhrase],
        model: str,
        output_prefix_uri: str | None = None,
    ) -> str:
        hotwords = _hotword_list(adaptation_phrases)
        tasks: dict[str, int] = {}
        engine = model or "16k_zh_en"
        for f in files:
            url = self._audio_url(f.uri)
            payload: dict[str, Any] = {
                "EngineModelType": engine,
                "ChannelNum": 1,
                "ResTextFormat": 2,
                "SourceType": 0,
                "Url": url,
                "SpeakerDiarization": 0,
                "ConvertNumMode": 1,
                "FilterDirty": 0,
                "FilterPunc": 0,
                "FilterModal": 0,
            }
            if hotwords:
                payload["HotwordList"] = hotwords
            response = _post("CreateRecTask", payload)
            task_id = int(response["Data"]["TaskId"])
            tasks[f.uri] = task_id
        logger.info("Tencent ASR submitted {} task(s) via {}", len(tasks), engine)
        return json.dumps({"engine": engine, "tasks": tasks}, ensure_ascii=False)

    def fetch_result(self, operation_name: str) -> list[FileResult] | None:
        data = json.loads(operation_name)
        tasks: dict[str, int] = data["tasks"]
        results: list[FileResult] = []
        for uri, task_id in tasks.items():
            response = _post("DescribeTaskStatus", {"TaskId": int(task_id)})
            status = response["Data"]["Status"]
            if status in (0, 1):
                return None
            if status == 3:
                err = response["Data"].get("ErrorMsg") or "recognition failed"
                raise RuntimeError(f"Tencent ASR task {task_id} failed: {err}")
            detail = response["Data"].get("ResultDetail") or []
            results.append(
                FileResult(
                    uri=uri,
                    segments=_parse_detail(detail),
                    language_detected="zh-Hant",
                    billed_seconds=float(response["Data"].get("AudioDuration") or 0),
                )
            )
        return results
