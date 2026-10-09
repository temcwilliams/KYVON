"""Voice: server-side speech-to-text. Text-to-speech happens on the device."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import enforce_rate, login_required, services
from kyvon.api.errors import ApiError
from kyvon.integrations.speech import MIME_TO_EXTENSION, SpeechError, sniff_audio
from kyvon.services.settings_service import get_settings
from kyvon.services.usage_service import UsageGate

bp = Blueprint("voice", __name__, url_prefix="/api/v1/voice")


@bp.get("/config")
@login_required
def config():
    svc = services()
    return jsonify(
        {
            "speech_to_text": svc.stt is not None,
            "text_to_speech": "device",
            "max_audio_bytes": svc.settings.max_audio_bytes,
            "max_seconds": 60,
            "voice_replies": get_settings(_session(), g.user.id).voice_replies,
        }
    )


def _session():
    from kyvon.api.deps import get_session

    return get_session()


@bp.post("/transcribe")
@login_required
def transcribe():
    enforce_rate("voice", 20)
    svc = services()
    if svc.stt is None:
        raise ApiError(409, "not_configured", "Speech-to-text is not available on this server.")
    upload = request.files.get("audio")
    if upload is None:
        raise ApiError(400, "invalid_request", "Send the recording as a form field named 'audio'.")

    declared = (upload.mimetype or "").split(";")[0].strip().lower()
    if declared not in MIME_TO_EXTENSION:
        raise ApiError(415, "unsupported_media", "That audio format is not supported.")
    limit = svc.settings.max_audio_bytes
    data = upload.stream.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "too_large", "That recording is too large.")
    if len(data) < 200:
        raise ApiError(400, "invalid_request", "That recording is empty.")
    container = sniff_audio(data)
    if container is None:
        raise ApiError(415, "unsupported_media", "That file does not look like audio.")

    gate = UsageGate(_session(), svc.settings, g.user.id) if svc.settings.hosted else None
    if gate is not None:
        gate.check("voice")

    language = (request.form.get("language") or "").strip().lower() or None
    if language is not None and not (2 <= len(language) <= 3 and language.isalpha()):
        raise ApiError(400, "invalid_request", "language must be a short code like 'en'.")
    try:
        text = svc.stt.transcribe(data, f"voice.{container}", language=language)
    except SpeechError as error:
        svc.error_log.log("Speech Error", str(error), "")
        raise ApiError(502, "transcription_failed", str(error)) from error
    if gate is not None:
        gate.record("voice")
    return jsonify({"text": text})
