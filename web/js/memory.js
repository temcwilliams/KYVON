// Viewing saved memories.

import { api } from "./api.js";
import { say } from "./ui.js";

export async function showMemory() {
    try {
        const data = await api("/memories");

        if (!data.memories || data.memories.length === 0) {
            say("I currently have no saved memories.");
            return;
        }

        let result = "RECENT MEMORIES\n\n";
        for (const item of data.memories) {
            result += `• ${item.memory}\n`;
        }
        say(result);
    } catch (error) {
        if (error.status !== 401) {
            say("Unable to access memory.");
        }
    }
}
