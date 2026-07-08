"""ASR provider registry — mirrors Voicebot-Platform's factory shape."""

from __future__ import annotations

from worker.asr.base import BatchASRAdapter
from worker.asr.gemini_audio import GeminiAudioASR
from worker.asr.google_batch import GoogleBatchASR
from worker.asr.qwen_asr import QwenASR
from worker.asr.tencent_asr import TencentASR

PROVIDERS = {
    "google": GoogleBatchASR,
    "gemini": GeminiAudioASR,
    "qwen": QwenASR,
    "tencent": TencentASR,
}


def create(provider: str = "google", **kwargs) -> BatchASRAdapter:
    try:
        cls = PROVIDERS[provider]
    except KeyError as e:
        raise ValueError(f"unknown ASR provider {provider!r}; known: {sorted(PROVIDERS)}") from e
    return cls(**kwargs)
