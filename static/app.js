const conversation = document.getElementById("conversation");
const input = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const micButton = document.getElementById("micButton");
const status = document.getElementById("status");
const listening = document.getElementById("listening");

let currentEnvironment = null;
let recognition = null;


// ============================================================
// MESSAGE DISPLAY
// ============================================================

function addMessage(speaker, text, type) {

    const message = document.createElement("div");

    message.className = `message ${type}-message`;

    message.innerHTML =
        `<span class="speaker">${speaker}:</span>
         <span>${escapeHtml(text)}</span>`;

    conversation.appendChild(message);

    conversation.scrollTop =
        conversation.scrollHeight;
}


function escapeHtml(text) {

    const div = document.createElement("div");

    div.textContent = text;

    return div.innerHTML;
}


// ============================================================
// LOCATION
// ============================================================

function requestLocation() {

    if (!navigator.geolocation) {

        addMessage(
            "Kyvon",
            "Location services are not supported by this browser.",
            "kyvon"
        );

        return;
    }

    listening.textContent =
        "REQUESTING LOCATION";

    navigator.geolocation.getCurrentPosition(

        async position => {

            const latitude =
                position.coords.latitude;

            const longitude =
                position.coords.longitude;

            try {

                const response = await fetch(
                    "/api/environment",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json"
                        },
                        body: JSON.stringify({
                            latitude,
                            longitude
                        })
                    }
                );

                const data =
                    await response.json();

                if (!response.ok) {

                    throw new Error(
                        data.error ||
                        "Unable to retrieve environment data."
                    );
                }

                currentEnvironment = {

                    latitude,
                    longitude,

                    location:
                        data.location,

                    weather:
                        data.weather
                };

                console.log(
                    "KYVON environment:",
                    currentEnvironment
                );

                status.textContent =
                    "ONLINE";

                listening.textContent =
                    "LOCATION READY";

            } catch (error) {

                console.error(error);

                listening.textContent =
                    "LOCATION ERROR";

            }

        },

        error => {

            console.error(
                "Location error:",
                error
            );

            status.textContent =
                "ONLINE";

            listening.textContent =
                "LOCATION DENIED";

            addMessage(
                "Kyvon",
                "I don't currently have permission to access your location. You can enable Location Services for this site in your iPad browser settings.",
                "kyvon"
            );
        },

        {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 300000
        }
    );
}


// ============================================================
// BUILD ENVIRONMENT INFORMATION
// ============================================================

function environmentText() {

    if (!currentEnvironment) {

        return (
            "No location information is currently available."
        );
    }

    const location =
        currentEnvironment.location;

    const weather =
        currentEnvironment.weather;

    return `
CURRENT LOCATION:
${location.display}

CITY:
${location.city}

STATE:
${location.state}

COUNTRY:
${location.country}

CURRENT WEATHER:
Condition: ${weather.condition}
Temperature: ${weather.temperature}°F
Feels like: ${weather.feels_like}°F
Humidity: ${weather.humidity}%
Precipitation: ${weather.precipitation} inches
Wind: ${weather.wind} mph

LOCAL TIME:
${weather.time}

TIME ZONE:
${weather.timezone}
`;
}


// ============================================================
// SEND MESSAGE
// ============================================================

async function sendMessage() {

    const message =
        input.value.trim();

    if (!message) return;

    addMessage(
        "You",
        message,
        "user"
    );

    input.value = "";

    status.textContent =
        "THINKING";

    listening.textContent =
        "PROCESSING";

    try {

        const response =
            await fetch(
                "/api/chat",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        message,

                        environment:
                            environmentText()
                    })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error ||
                "KYVON request failed."
            );
        }

        addMessage(
            "Kyvon",
            data.response,
            "kyvon"
        );

    } catch (error) {

        addMessage(
            "Kyvon",
            "I encountered an error: " +
            error.message,
            "kyvon"
        );

    } finally {

        status.textContent =
            "ONLINE";

        listening.textContent =
            "STANDBY";
    }
}


// ============================================================
// DIAGNOSTICS
// ============================================================

async function runDiagnostics() {

    addMessage(
        "Kyvon",
        "Running system diagnostics...",
        "kyvon"
    );

    try {

        const response =
            await fetch("/api/status");

        const data =
            await response.json();

        let result =
            "SYSTEM DIAGNOSTICS\n\n";

        for (
            const item
            of data.diagnostics
        ) {

            result +=
                `[${item.status}] ` +
                `${item.name}: ` +
                `${item.details}\n`;
        }

        if (currentEnvironment) {

            result +=
                "\nLOCATION SYSTEM: ONLINE\n";

            result +=
                `Location: ${currentEnvironment.location.display}\n`;

            result +=
                `Weather: ${currentEnvironment.weather.condition}\n`;

            result +=
                `Temperature: ${currentEnvironment.weather.temperature}°F\n`;

        } else {

            result +=
                "\nLOCATION SYSTEM: WAITING FOR PERMISSION\n";
        }

        addMessage(
            "Kyvon",
            result,
            "kyvon"
        );

    } catch (error) {

        addMessage(
            "Kyvon",
            "Unable to run diagnostics.",
            "kyvon"
        );
    }
}


// ============================================================
// MEMORY
// ============================================================

async function showMemory() {

    try {

        const response =
            await fetch("/api/memory");

        const data =
            await response.json();

        if (
            !data.memories ||
            data.memories.length === 0
        ) {

            addMessage(
                "Kyvon",
                "I currently have no saved memories.",
                "kyvon"
            );

            return;
        }

        let result =
            "RECENT MEMORIES\n\n";

        for (
            const item
            of data.memories
        ) {

            result +=
                `• ${item.memory}\n`;
        }

        addMessage(
            "Kyvon",
            result,
            "kyvon"
        );

    } catch {

        addMessage(
            "Kyvon",
            "Unable to access memory.",
            "kyvon"
        );
    }
}


// ============================================================
// CLEAR
// ============================================================

function clearConversation() {

    conversation.innerHTML = "";

    addMessage(
        "Kyvon",
        "Conversation cleared.",
        "kyvon"
    );
}


// ============================================================
// BUTTONS
// ============================================================

sendButton.addEventListener(
    "click",
    sendMessage
);


input.addEventListener(
    "keydown",
    event => {

        if (event.key === "Enter") {

            sendMessage();
        }
    }
);


// ============================================================
// VOICE INPUT
// ============================================================

if ("webkitSpeechRecognition" in window) {

    recognition =
        new webkitSpeechRecognition();

    recognition.continuous =
        false;

    recognition.interimResults =
        false;

    recognition.lang =
        "en-US";


    recognition.onstart = () => {

        listening.textContent =
            "LISTENING";

        status.textContent =
            "LISTENING";

        micButton.textContent =
            "⏹️";
    };


    recognition.onresult =
        event => {

            const transcript =
                event.results[0][0].transcript;

            input.value =
                transcript;

            sendMessage();
        };


    recognition.onerror =
        () => {

            listening.textContent =
                "STANDBY";

            status.textContent =
                "ONLINE";

            micButton.textContent =
                "🎙️";
        };


    recognition.onend =
        () => {

            listening.textContent =
                "STANDBY";

            status.textContent =
                "ONLINE";

            micButton.textContent =
                "🎙️";
        };


    micButton.addEventListener(
        "click",
        () => {

            recognition.start();
        }
    );

} else {

    micButton.addEventListener(
        "click",
        () => {

            addMessage(
                "Kyvon",
                "Voice input is not supported by this browser.",
                "kyvon"
            );
        }
    );
}


// ============================================================
// STARTUP
// ============================================================

runDiagnostics();


// Ask the iPad for location permission
requestLocation();