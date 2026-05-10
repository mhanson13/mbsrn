import { normalizeError } from "./errors";

describe("normalizeError", () => {
  it("returns Error instance for null input", () => {
    const normalized = normalizeError(null, "Fallback message");
    expect(normalized).toBeInstanceOf(Error);
    expect(normalized.message).toBe("Fallback message");
  });

  it("returns Error instance for undefined input", () => {
    const normalized = normalizeError(undefined, "Fallback message");
    expect(normalized).toBeInstanceOf(Error);
    expect(normalized.message).toBe("Fallback message");
  });

  it("uses object message when provided", () => {
    const normalized = normalizeError({ message: "Provider failure" }, "Fallback message");
    expect(normalized).toBeInstanceOf(Error);
    expect(normalized.message).toBe("Provider failure");
  });
});
