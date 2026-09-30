// Minimal publish/subscribe plus shared client state.

const listeners = new Map();

export const state = {
    conversationId: null,
    busy: false,
};

export function on(event, handler) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(handler);
    return () => listeners.get(event).delete(handler);
}

export function emit(event, detail) {
    for (const handler of listeners.get(event) || []) {
        try {
            handler(detail);
        } catch (error) {
            console.error(`Handler for "${event}" failed`, error);
        }
    }
}
