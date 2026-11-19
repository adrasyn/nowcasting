import { defineConfig, devices } from "@playwright/test";

const prebuilt = process.env.NOWCAST_PREBUILT === "1";
// A prebuilt candidate must be tested locally, never an older public build.
const publicBase = prebuilt ? undefined : process.env.NOWCAST_PUBLIC_BASE_URL;
const port = Number(process.env.NOWCAST_TEST_PORT || 3000);
if (!Number.isInteger(port) || port < 1 || port > 65535)
  throw new Error("Invalid NOWCAST_TEST_PORT");

export default defineConfig({
  testDir: "./tests",
  timeout: 30000,
  workers: process.env.CI ? 1 : undefined,
  use: {
    baseURL: publicBase || `http://127.0.0.1:${port}`,
    headless: true,
  },
  projects: [
    {
      name: "chromium",
      testIgnore: "**/deployment-smoke.spec.ts",
      use: {
        browserName: "chromium",
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
          : {},
      },
    },
    {
      name: "deployment-smoke",
      testMatch: "**/deployment-smoke.spec.ts",
      use: {
        browserName: "chromium",
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
          : {},
      },
    },
    {
      name: "webkit-iphone",
      testMatch: [
        "**/evolution-visibility.spec.ts",
        "**/evolution-legend.spec.ts",
        "**/evolution-axis.spec.ts",
      ],
      use: { ...devices["iPhone 13"], browserName: "webkit" },
    },
  ],
  webServer: publicBase
    ? undefined
    : {
        command:
          (prebuilt
            ? ""
            : "npm test && npm run build && ") +
          `npx serve out -p ${port} --no-clipboard`,
        port,
        timeout: 120_000,
        reuseExistingServer: !process.env.CI,
      },
});
