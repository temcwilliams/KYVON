"""Voice providers, kept behind small interfaces so they can be swapped.

* ``SpeechToText`` - turns a recording into text. Default: Whisper on Groq (same provider and
  key as the language model).
* Text-to-speech is done by the client (browser speech synthesis / iOS AVSpeechSynthesizer): it
  needs no server round trip, works offline and keeps replies off third-party services. The
  ``TextToSpeech`` interface exists so a server-side provider can be added later.

Uploaded audio is validated by its actual bytes (not just the declared type) before it is
forwarded anywhere.
"""

from __future__ import annotations

from typing import Protocol

from groq import Groq

MIME_TO_EXTENSION = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
}


class SpeechError(RuntimeError):
    pass


class SpeechToText(Protocol):
    def transcribe(self, audio: bytes, filename: str, *, language: str | None = None) -> str: ...


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> bytes: ...


def sniff_audio(data: bytes) -> str | None:
    """The container format from the leading bytes, or None if it is not recognised audio."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[4:8] == b"ftyp":
        return "m4a"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"fLaC":
        return "flac"
    return None


class GroqWhisper:
    def __init__(
        self, api_key: str, model: str, *, client: Groq | None = None, timeout: float = 60.0
    ):
        self._client = client or Groq(api_key=api_key, timeout=timeout)
        self._model = model

    def transcribe(self, audio: bytes, filename: str, *, language: str | None = None) -> str:
        kwargs = {"file": (filename, audio), "model": self._model, "response_format": "json"}
        if language:
            kwargs["language"] = language
        try:
            result = self._client.audio.transcriptions.create(**kwargs)
        except Exception as error:
            raise SpeechError(f"Transcription failed ({type(error).__name__}).") from error
        return (getattr(result, "text", "") or "").strip()
