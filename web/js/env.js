// Location and weather ("environment") for the assistant.

import { api } from "./api.js";
import { say, setListening, setStatus } from "./ui.js";

let currentEnvironment = null;

export function getEnvironment() {
    return currentEnvironment;
}

export function requestLocation() {
    if (!navigator.geolocation) {
        say("Location services are not supported by this browser.");
        return;
    }

    setListening("REQUESTING LOCATION");

    navigator.geolocation.getCurrentPosition(
        async position => {
            const { latitude, longitude } = position.coords;
            try {
                const data = await api("/environment", {
                    method: "POST",
                    body: { latitude, longitude },
                });
                currentEnvironment = {
                    latitude,
                    longitude,
                    location: data.location,
                    weather: data.weather,
                };
                setStatus("ONLINE");
                setListening("LOCATION READY");
            } catch (error) {
                console.error(error);
                setListening("LOCATION ERROR");
            }
        },
        error => {
            console.error("Location error:", error);
            setStatus("ONLINE");
            setListening("LOCATION DENIED");
            say(
                "I don't currently have permission to access your location. " +
                    "You can enable Location Services for this site in your browser settings."
            );
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 300000 }
    );
}

// Text block sent with each chat message (same format the prototype used).
export function environmentText() {
    if (!currentEnvironment) {
        return "No location information is currently available.";
    }

    const { location, weather } = currentEnvironment;

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
