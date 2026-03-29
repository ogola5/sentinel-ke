import { chromium } from "playwright";

const USERNAME = "admin";
const PASSWORD = "Sentinel@Admin2025!";

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROME_PATH ?? "/usr/bin/google-chrome",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();

  await page.goto("http://localhost:3000/");
  await page.getByRole("button", { name: /open secure login/i }).click();
  await page.getByPlaceholder("Enter your assigned username").fill(USERNAME);
  await page.getByPlaceholder("••••••••••••").fill(PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForTimeout(2500);

  const result = await page.evaluate(async () => {
    const token = window.localStorage.getItem("sentinel_access_token");
    const headers = new Headers({ Accept: "application/json" });
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const now = new Date();
    const start = new Date(now.getTime() - 60 * 60 * 1000);
    const urls = [
      ["ready", "http://localhost:8000/ready"],
      ["events", "http://localhost:8000/v1/events/search?size=120"],
      [
        "timeline",
        `http://localhost:8000/v1/events/timeline?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(
          now.toISOString(),
        )}&interval=5m`,
      ],
      ["campaigns", "http://localhost:8000/v1/campaigns?limit=25&offset=0"],
      ["ddos", "http://localhost:8000/v1/ddos/alerts?limit=20&offset=0"],
      ["infra", "http://localhost:8000/v1/infra/clusters?limit=10&offset=0"],
      ["summary", "http://localhost:8000/v1/ai/indicators/summary?days=7"],
    ];

    return Promise.all(
      urls.map(async ([label, url]) => {
        const startedAt = performance.now();
        try {
          const response = await fetch(url, { headers });
          const text = await response.text();
          return {
            label,
            status: response.status,
            ms: Math.round(performance.now() - startedAt),
            size: text.length,
          };
        } catch (error) {
          return {
            label,
            status: "error",
            ms: Math.round(performance.now() - startedAt),
            error: error instanceof Error ? error.message : String(error),
          };
        }
      }),
    );
  });

  console.log(JSON.stringify(result, null, 2));
  await browser.close();
}

void main();
