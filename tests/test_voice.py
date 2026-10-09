"""Voice: upload validation, transcription, errors, and the client's voice module."""

import io
import re
from dataclasses import replace
from pathlib import Path

import pytest

from kyvon.integrations.speech import GroqWhisper, SpeechError, sniff_audio
from tests.conftest import make_app

WEB = Path(__file__).resolve().parent.parent / "web"
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 400
M4A = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 400
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 400
OGG = b"OggS" + b"\x00" * 400
MP3 = b"ID3\x04" + b"\x00" * 400


def upload(client, data=WEBM, mime="audio/webm", **form):
    return client.post(
        "/api/v1/voice/transcribe",
        data={"audio": (io.BytesIO(data), "rec.webm", mime), **form},
        content_type="multipart/form-data",
    )


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (WEBM, "webm"),
        (M4A, "m4a"),
        (WAV, "wav"),
        (OGG, "ogg"),
        (MP3, "mp3"),
        (b"fLaC" + b"0" * 10, "flac"),
    ],
)
def test_sniffing_recognises_audio_containers(data, kind):
    assert sniff_audio(data) == kind


@pytest.mark.parametrize(
    "data", [b"", b"<html>", b"MZ\x90\x00", b"#!/bin/sh\nrm -rf /", b"PK\x03\x04", b"%PDF-1.7"]
)
def test_sniffing_rejects_everything_else(data):
    assert sniff_audio(data) is None


def test_transcribe(client, fake_stt):
    response = upload(client, language="en")
    assert response.status_code == 200 and response.get_json() == {
        "text": "hello from the recording"
    }
    assert fake_stt.calls == [{"size": len(WEBM), "filename": "voice.webm", "language": "en"}]


@pytest.mark.parametrize(
    ("data", "mime", "ext"),
    [
        (M4A, "audio/mp4", "m4a"),
        (WAV, "audio/wav", "wav"),
        (WEBM, "audio/webm;codecs=opus", "webm"),
    ],
)
def test_formats_and_codec_parameters(client, fake_stt, data, mime, ext):
    assert upload(client, data, mime).status_code == 200
    assert fake_stt.calls[-1]["filename"] == f"voice.{ext}"


def test_filename_sent_onward_comes_from_the_bytes_not_the_client(client, fake_stt):
    client.post(
        "/api/v1/voice/transcribe",
        data={"audio": (io.BytesIO(WEBM), "../../etc/passwd", "audio/webm")},
        content_type="multipart/form-data",
    )
    assert fake_stt.calls[-1]["filename"] == "voice.webm"


@pytest.mark.parametrize(
    ("data", "mime", "status"),
    [
        (WEBM, "text/html", 415),
        (WEBM, "application/octet-stream", 415),
        (b"<script>alert(1)</script>" * 20, "audio/webm", 415),  # claims audio, is not
        (b"\x00" * 50, "audio/webm", 400),
        (WEBM, "application/x-msdownload", 415),
    ],
)
def test_bad_uploads(client, fake_stt, data, mime, status):
    assert upload(client, data, mime).status_code == status
    assert fake_stt.calls == []


def test_missing_field_and_bad_language(client, fake_stt):
    assert (
        client.post(
            "/api/v1/voice/transcribe", data={}, content_type="multipart/form-data"
        ).status_code
        == 400
    )
    assert upload(client, language="english-please").status_code == 400
    assert upload(client, language="e1").status_code == 400
    assert fake_stt.calls == []


def test_size_limit(settings, fake_llm, fake_environment):
    from kyvon.services import auth_service

    small = replace(settings, max_audio_bytes=10_000)
    app = make_app(small, llm=fake_llm, environment=fake_environment)
    with app.extensions["kyvon"].session_factory() as s:
        auth_service.create_owner(s, "owner", "correct horse battery")
    c = app.test_client()
    token = c.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "correct horse battery"}
    ).get_json()["token"]
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    response = upload(c, WEBM[:4] + b"\x00" * 20_000)
    assert response.status_code == 413 and response.get_json()["error"]["code"] == "too_large"


def test_provider_failure_is_a_502_and_logged(client, fake_stt, settings):
    fake_stt.error = SpeechError("Transcription failed (APIError).")
    response = upload(client)
    assert (
        response.status_code == 502
        and response.get_json()["error"]["code"] == "transcription_failed"
    )
    assert "Speech Error" in settings.error_log.read_text()


def test_unavailable_provider(client, app):
    app.extensions["kyvon"].stt = None
    assert upload(client).status_code == 409
    assert client.get("/api/v1/voice/config").get_json()["speech_to_text"] is False


def test_config_endpoint(client):
    data = client.get("/api/v1/voice/config").get_json()
    assert data["speech_to_text"] is True and data["text_to_speech"] == "device"
    assert data["max_seconds"] == 60 and data["voice_replies"] is False
    client.patch("/api/v1/settings", json={"voice_replies": True})
    assert client.get("/api/v1/voice/config").get_json()["voice_replies"] is True


def test_requires_auth(anon_client, owner):
    assert (
        anon_client.post(
            "/api/v1/voice/transcribe", data={}, content_type="multipart/form-data"
        ).status_code
        == 401
    )
    assert anon_client.get("/api/v1/voice/config").status_code == 401


def test_text_chat_works_without_any_voice_provider(client, app):
    app.extensions["kyvon"].stt = None
    assert client.post("/api/v1/chat", json={"message": "hello"}).status_code == 200


def test_oversized_json_is_refused(client, settings):
    body = '{"message": "' + "x" * (settings.max_request_bytes + 10) + '"}'
    assert (
        client.post("/api/v1/chat", data=body, content_type="application/json").status_code == 413
    )


# ------------------------------------------------------------ the Whisper adapter


class FakeGroqAudio:
    def __init__(self, text="  Hi there  ", error=None):
        self.calls = []
        self.error = error
        transcriptions = type("T", (), {})()
        transcriptions.create = self._create
        self.audio = type("A", (), {"transcriptions": transcriptions})()
        self._text = text

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return type("R", (), {"text": self._text})()


def test_whisper_adapter():
    fake = FakeGroqAudio()
    text = GroqWhisper("k", "whisper-large-v3-turbo", client=fake).transcribe(
        b"audio", "voice.webm", language="en"
    )
    assert text == "Hi there"
    assert fake.calls == [
        {
            "file": ("voice.webm", b"audio"),
            "model": "whisper-large-v3-turbo",
            "response_format": "json",
            "language": "en",
        }
    ]


def test_whisper_adapter_hides_provider_details():
    fake = FakeGroqAudio(error=RuntimeError("secret key gsk_abcdef in message"))
    with pytest.raises(SpeechError) as info:
        GroqWhisper("k", "m", client=fake).transcribe(b"a", "voice.webm")
    assert "gsk_" not in str(info.value)


# ------------------------------------------------------------ client module (static checks)


def test_voice_module_is_modular_and_optional():
    source = (WEB / "js" / "voice.js").read_text()
    assert (
        "/voice/transcribe" in source and "speechSynthesis" in source and "MediaRecorder" in source
    )
    assert "webkitSpeechRecognition" in source  # fallback where server transcription is unavailable
    assert "cancelSpeech" in source and "Escape" in source  # interruption
    main = (WEB / "js" / "main.js").read_text()
    assert "initVoice" in main
    html = (WEB / "index.html").read_text()
    assert re.search(r'id="micButton"[^>]*aria-label=', html)
