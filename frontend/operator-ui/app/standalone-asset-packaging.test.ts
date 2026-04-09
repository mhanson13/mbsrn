import { readFileSync } from "node:fs";
import { join } from "node:path";

describe("standalone asset packaging", () => {
  it("copies public assets into the runtime image for root-relative image URLs", () => {
    const dockerfilePath = join(process.cwd(), "Dockerfile");
    const dockerfileContent = readFileSync(dockerfilePath, "utf-8");

    expect(dockerfileContent).toContain("COPY --from=builder /app/public ./public");
  });
});
