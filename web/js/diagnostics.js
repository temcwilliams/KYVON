// The SYSTEM button.

import { api } from "./api.js";
import { getEnvironment } from "./env.js";
import { say } from "./ui.js";

// ``deep`` also tests the AI connection (costs one model call).
export async function runDiagnostics({ deep = false } = {}) {
    say("Running system diagnostics...");

    try {
        const data = await api(`/status${deep ? "?deep=1" : ""}`);

        let result = "SYSTEM DIAGNOSTICS\n\n";
        for (const item of data.diagnostics) {
            result += `[${item.status}] ${item.name}: ${item.details}\n`;
        }

        const environment = getEnvironment();
        if (environment) {
            result += "\nLOCATION SYSTEM: ONLINE\n";
            result += `Location: ${environment.location.display}\n`;
            result += `Weather: ${environment.weather.condition}\n`;
            result += `Temperature: ${environment.weather.temperature}°F\n`;
        } else {
            result += "\nLOCATION SYSTEM: WAITING FOR PERMISSION\n";
        }

        say(result);
    } catch (error) {
        if (error.status !== 401) {
            say("Unable to run diagnostics.");
        }
    }
}
