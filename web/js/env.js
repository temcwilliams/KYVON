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
