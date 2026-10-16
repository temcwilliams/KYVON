// The SYSTEM button.

import { api } from "./api.js";
import { getEnvironment } from "./env.js";
import { say } from "./ui.js";

// ``deep`` also tests the AI connection (costs one model call).
export async function runDiagnostics({ deep = false } = {}) {
    say("Checking system status...");

    try {
        const data = await api(`/status${deep ? "?deep=1" : ""}`);

        let result = "System status\n\n";
        for (const item of data.diagnostics) {
            result += `${item.name}: ${item.details} (${String(item.status).toLowerCase()})\n`;
        }

        const environment = getEnvironment();
        if (environment) {
            result += "\n";
            result += `Location: ${environment.location.display}\n`;
            result += `Weather: ${environment.weather.condition}\n`;
            result += `Temperature: ${environment.weather.temperature}°F\n`;
        } else {
            result += "\nLocation: not shared yet. Allow location access in your browser to use it.\n";
        }

        say(result);
    } catch (error) {
        if (error.status !== 401) {
            say("Unable to run diagnostics.");
        }
    }
}
