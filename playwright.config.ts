import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30000,
  use: {
    baseURL: process.env.NOWCAST_PUBLIC_BASE_URL ?? "http://localhost:3000",
    headless: true,
  },
  projects: [
    {
      name: "chromium",
      use: {
        browserName: "chromium",
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
          : {},
      },
    },
    {
      name: "webkit-iphone",
      testMatch: ["**/evolution-visibility.spec.ts", "**/evolution-legend.spec.ts"],
      use: { ...devices["iPhone 13"], browserName: "webkit" },
    },
  ],
  webServer: process.env.NOWCAST_PUBLIC_BASE_URL
    ? undefined
    : {
        command:
          "npm test && npm run build && npx serve out -p 3000 --no-clipboard",
        port: 3000,
        timeout: 120_000,
        reuseExistingServer: !process.env.CI,
      },
});
