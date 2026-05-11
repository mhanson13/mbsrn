const FALLBACK_PATHNAME = "unknown";
const FALLBACK_MESSAGE = "Route render failure";
const FALLBACK_CLASS_NAME = "UnknownError";
const MAX_PATHNAME_LENGTH = 160;
const MAX_MESSAGE_LENGTH = 160;
const MAX_CLASS_LENGTH = 64;

function coerceString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function sanitizePathname(pathname: unknown): string {
  const raw = coerceString(pathname);
  if (!raw) {
    return FALLBACK_PATHNAME;
  }
  const withoutQueryOrHash = raw.split("?")[0].split("#")[0].trim();
  if (!withoutQueryOrHash) {
    return FALLBACK_PATHNAME;
  }
  const bounded = withoutQueryOrHash.slice(0, MAX_PATHNAME_LENGTH);
  return bounded.startsWith("/") ? bounded : `/${bounded}`;
}

export function sanitizeDiagnosticMessage(
  message: unknown,
  fallbackMessage: string = FALLBACK_MESSAGE,
): string {
  const fallback = coerceString(fallbackMessage) || FALLBACK_MESSAGE;
  const raw = coerceString(message);
  if (!raw) {
    return fallback;
  }

  const redacted = raw.replace(
    /([?&](?:code|state|id_token|access_token|refresh_token)=)[^&\s]+/gi,
    "$1[redacted]",
  );
  return redacted.slice(0, MAX_MESSAGE_LENGTH);
}

export function deriveErrorClassName(error: unknown): string {
  if (error && typeof error === "object" && !Array.isArray(error)) {
    const candidate = error as { name?: unknown };
    const name = coerceString(candidate.name);
    if (name) {
      return name.slice(0, MAX_CLASS_LENGTH);
    }
  }
  return FALLBACK_CLASS_NAME;
}
