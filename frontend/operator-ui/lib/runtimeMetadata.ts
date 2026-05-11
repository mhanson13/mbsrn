const DEFAULT_PUBLIC_APP_VERSION = "unknown";
const MAX_PUBLIC_APP_VERSION_LENGTH = 80;
const SAFE_PUBLIC_APP_VERSION_PATTERN = /^[A-Za-z0-9._:@/+\-]+$/;

export function normalizePublicAppVersion(rawVersion: unknown): string {
  if (typeof rawVersion !== "string") {
    return DEFAULT_PUBLIC_APP_VERSION;
  }
  const trimmed = rawVersion.trim();
  if (!trimmed) {
    return DEFAULT_PUBLIC_APP_VERSION;
  }
  if (trimmed.length > MAX_PUBLIC_APP_VERSION_LENGTH) {
    return DEFAULT_PUBLIC_APP_VERSION;
  }
  if (!SAFE_PUBLIC_APP_VERSION_PATTERN.test(trimmed)) {
    return DEFAULT_PUBLIC_APP_VERSION;
  }
  return trimmed;
}

export function getPublicAppVersion(): string {
  return normalizePublicAppVersion(process.env.NEXT_PUBLIC_APP_VERSION);
}
