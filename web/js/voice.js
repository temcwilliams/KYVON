// Voice: dictation in, spoken replies out. Entirely optional: text chat never depends on it.
//
// Input: records with MediaRecorder and sends the audio to the server for transcription
// (Whisper). Where that is unavailable, falls back to the browser's own speech recognition.
// Output: the browser's speech synthesis (on the device; nothing is sent anywhere).
// States: idle -> recording -> transcribing -> idle, and speaking (interruptible at any time).

import { api } from "./api.js";
import { on } from "./state.js";
import { say, setListening, setStatus } from "./ui.js";

const micButton = document.getElementById("micButton");
const input = document.getElementById("messageInput");

const MAX_SECONDS = 60;
let config = { speech_to_text: false, voice_replies: false };
let state = "idle";
let recorder = null;
let stream = null;
let chunks = [];
let stopTimer = null;
let discard = false;
let sendHandler = () => {};
let recognition = null;

function setState(next) {
    state = next;
    const labels = { idle: "STANDBY", recording: "LISTENING", transcribing: "TRANSCRIBING", speaking: "SPEAKING" };
    setListening(labels[next]);
    setStatus(next === "idle" ? "ONLINE" : labels[next]);
    micButton.textContent = { idle: "🎙️", recording: "⏹️", transcribing: "…", speaking: "🔇" }[next];
    micButton.setAttribute("aria-pressed", String(next === "recording"));
    micButton.setAttribute(
        "aria-label",
        { idle: "Voice input", recording: "Stop recording", transcribing: "Transcribing", speaking: "Stop speaking" }[next]
    );
}

export async function refreshVoiceConfig() {
    try {
        config = await api("/voice/config");
    } catch {
        config = { speech_to_text: false, voice_replies: false };
    }
}

// ---- speaking -----------------------------------------------------------------------

function plainText(text) {
    return text.replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim();
}

export function speak(text) {
    if (!("speechSynthesis" in window) || !text) return;
    cancelSpeech();
    const utterance = new SpeechSynthesisUtterance(plainText(text));
    utterance.onend = utterance.onerror = () => {
        if (state === "speaking") setState("idle");
    };
    setState("speaking");
    window.speechSynthesis.speak(utterance);
}

export function cancelSpeech() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    if (state === "speaking") setState("idle");
}

// ---- recording ----------------------------------------------------------------------

function pickMimeType() {
    for (const type of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
        if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) return type;
    }
    return "";
}

function releaseMic() {
    if (stopTimer) window.clearTimeout(stopTimer);
    stopTimer = null;
    if (stream) for (const track of stream.getTracks()) track.stop();
    stream = null;
}

async function startRecording() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
        say("I can't use the microphone. Allow microphone access for this site in your browser settings, then try again.");
        return;
    }
    const mimeType = pickMimeType();
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunks = [];
    discard = false;
    recorder.ondataavailable = event => {
        if (event.data.size) chunks.push(event.data);
    };
    recorder.onstop = () => finishRecording(recorder.mimeType || mimeType || "audio/webm");
    recorder.start();
    setState("recording");
    stopTimer = window.setTimeout(stopRecording, MAX_SECONDS * 1000);
}

function stopRecording() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
}

async function finishRecording(mimeType) {
    releaseMic();
    const blob = new Blob(chunks, { type: mimeType });
    chunks = [];
    if (discard || blob.size < 1000) {
        setState("idle");
        return;
    }
    setState("transcribing");
    try {
        const form = new FormData();
        form.append("audio", blob, "voice");
        const data = await api("/voice/transcribe", { method: "POST", form });
        if (data.text) {
            input.value = data.text;
            setState("idle");
            sendHandler();
            return;
        }
        say("I couldn't make out any speech. Try again a little closer to the microphone.");
    } catch (error) {
        if (error.status !== 401) say(`I couldn't transcribe that: ${error.message}`);
    }
    setState("idle");
}

// ---- fallback: the browser's own recognition ---------------------------------------------

function startBrowserRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
        say("Voice input isn't available in this browser. You can still type to me.");
        return;
    }
    recognition = new Recognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.onstart = () => setState("recording");
    recognition.onresult = event => {
        input.value = event.results[0][0].transcript;
        sendHandler();
    };
    recognition.onerror = recognition.onend = () => {
        recognition = null;
        if (state === "recording") setState("idle");
    };
    recognition.start();
}

// ---- wiring ------------------------------------------------------------------------

export function cancelVoice() {
    discard = true;
    if (recognition) recognition.abort();
    stopRecording();
    releaseMic();
    cancelSpeech();
    if (state !== "transcribing") setState("idle");
}

export function initVoice(onTranscript) {
    sendHandler = onTranscript;
    setState("idle");

    micButton.addEventListener("click", async () => {
        if (state === "speaking") return cancelSpeech();
        if (state === "recording") {
            if (recognition) recognition.stop();
            else stopRecording();
            return;
        }
        if (state !== "idle") return;
        if (!config.speech_to_text) await refreshVoiceConfig();
        const canRecord = config.speech_to_text && navigator.mediaDevices && window.MediaRecorder;
        if (canRecord) await startRecording();
        else startBrowserRecognition();
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && state !== "idle") cancelVoice();
    });

    // A new message or reply interrupts speech; finished replies are read aloud if enabled.
    on("turn:start", cancelSpeech);
    on("turn:done", data => {
        if (config.voice_replies && data && data.message) speak(data.message.content);
    });
    on("connection:lost", cancelVoice);
}
