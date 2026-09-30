// Voice input (browser speech recognition; availability varies by browser).

import { say, setListening, setStatus } from "./ui.js";

const micButton = document.getElementById("micButton");
const input = document.getElementById("messageInput");

export function initVoice(onTranscript) {
    if (!("webkitSpeechRecognition" in window)) {
        micButton.addEventListener("click", () => {
            say("Voice input is not supported by this browser.");
        });
        return;
    }

    const recognition = new window.webkitSpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    const idle = () => {
        setListening("STANDBY");
        setStatus("ONLINE");
        micButton.textContent = "🎙️";
    };

    recognition.onstart = () => {
        setListening("LISTENING");
        setStatus("LISTENING");
        micButton.textContent = "⏹️";
    };

    recognition.onresult = event => {
        input.value = event.results[0][0].transcript;
        onTranscript();
    };

    recognition.onerror = idle;
    recognition.onend = idle;

    micButton.addEventListener("click", () => recognition.start());
}

