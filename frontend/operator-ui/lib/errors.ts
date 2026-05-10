const DEFAULT_FALLBACK_MESSAGE = "Unexpected application error.";
const MAX_ERROR_MESSAGE_LENGTH = 240;

function normalizeMessage(value: unknown, fallbackMessage: string): string {
  if (typeof value !== "string") {
    return fallbackMessage;
  }
  const normalized = value.trim();
  if (!normalized) {
    return fallbackMessage;
  }
  if (normalized.length <= MAX_ERROR_MESSAGE_LENGTH) {
    return normalized;
  }
  return normalized.slice(0, MAX_ERROR_MESSAGE_LENGTH);
}

function messageFromErrorLikeObject(error: unknown): string | null {
  if (!error || typeof error !== "object" || Array.isArray(error)) {
    return null;
  }
  const candidate = error as { message?: unknown };
  if (typeof candidate.message !== "string") {
    return null;
  }
  const normalized = candidate.message.trim();
  return normalized.length > 0 ? normalized : null;
}

export function normalizeError(error: unknown, fallbackMessage: string = DEFAULT_FALLBACK_MESSAGE): Error {
  const safeFallbackMessage = normalizeMessage(fallbackMessage, DEFAULT_FALLBACK_MESSAGE);

  if (error instanceof Error) {
    const normalizedMessage = normalizeMessage(error.message, safeFallbackMessage);
    if (normalizedMessage === error.message) {
      return error;
    }
    const normalizedError = new Error(normalizedMessage);
    normalizedError.name = error.name || "Error";
    return normalizedError;
  }

  if (typeof error === "string") {
    return new Error(normalizeMessage(error, safeFallbackMessage));
  }

  const objectMessage = messageFromErrorLikeObject(error);
  if (objectMessage) {
    return new Error(normalizeMessage(objectMessage, safeFallbackMessage));
  }

  return new Error(safeFallbackMessage);
}
