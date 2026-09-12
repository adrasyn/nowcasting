import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "node",
    // tests/site.spec.ts is a Playwright e2e spec (run by `npm run test:e2e`).
    // Vitest was collecting it, failing to execute a playwright TestType, and
    // reporting a permanent red — which trains everyone to ignore the suite.
    // `.worktrees/` holds other branches' checkouts of this same repo. Their
    // copies of these files were being collected and run, and the loader
    // resolves `data/` from the working directory, so another branch's older
    // suite was asserting on THIS branch's payloads — a red that says nothing
    // about either branch.
    exclude: ["**/node_modules/**", "**/dist/**", "**/.next/**", "tests/**",
              "**/.worktrees/**"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
