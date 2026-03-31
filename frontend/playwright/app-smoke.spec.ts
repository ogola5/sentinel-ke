import { spawnSync } from "node:child_process";

import { expect, test, type Page } from "@playwright/test";

const OUTPUT_DIR = "test-artifacts";
const BROWSER_PATH =
  process.env.PLAYWRIGHT_CHROME_PATH ??
  process.env.PLAYWRIGHT_BROWSER_PATH ??
  "/usr/bin/google-chrome";

function browserLaunchProbe(): { ok: boolean; detail: string } {
  const probe = spawnSync(
    BROWSER_PATH,
    ["--headless", "--no-sandbox", "--disable-gpu", "--dump-dom", "about:blank"],
    {
      timeout: 5000,
      encoding: "utf8",
      stdio: "pipe",
    },
  );
  if (probe.status === 0 && !probe.error) {
    return { ok: true, detail: "browser launch probe passed" };
  }
  const stderr = String(probe.stderr || probe.error?.message || "").trim();
  const reason = stderr || `status=${String(probe.status)} signal=${String(probe.signal)}`;
  return { ok: false, detail: reason.slice(0, 240) };
}

const browserProbe = browserLaunchProbe();
test.skip(
  !browserProbe.ok,
  `Browser automation is unavailable in this environment. Probe failed for ${BROWSER_PATH}: ${browserProbe.detail}`,
);

async function login(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /open secure login/i })).toBeVisible();
  await page.getByRole("button", { name: /open secure login/i }).click();

  await expect(page.getByText("Secure Sign-In")).toBeVisible();
  await page.getByPlaceholder("Enter your assigned username").fill("admin");
  await page.getByPlaceholder("••••••••••••").fill("Sentinel@Admin2025!");
  await page.getByRole("button", { name: /^sign in$/i }).click();

  await expect(page.getByRole("heading", { name: /national command centre/i })).toBeVisible({ timeout: 20000 });
}

async function openSystemNav(page: Page) {
  await page.locator("aside").getByRole("button", { name: /^platform$/i }).click();
}

test("landing login, command, and GNN navigation work", async ({ page }) => {
  await login(page);

  await expect(page.getByRole("heading", { name: /national command centre/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /first moves/i })).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/01-command.png`, fullPage: true });

  await page.getByRole("button", { name: /open gnn intelligence/i }).first().click();
  await expect(page.getByRole("heading", { name: /gnn intelligence hub/i })).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/02-gnn.png`, fullPage: true });

  await expect(page.getByText(/api 500: internal_server_error/i)).toHaveCount(0);
});

test("federation screen loads from the system drawer", async ({ page }) => {
  await login(page);
  await openSystemNav(page);

  await page.getByRole("button", { name: /federation/i }).click();
  await expect(page.getByRole("heading", { name: /federation network/i })).toBeVisible();
  await expect(page.getByText(/hub sees/i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/03-federation.png`, fullPage: true });
});

test("command agency network can trigger a shared federation scenario", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: /agency network/i }).click();
  await expect(page.getByRole("heading", { name: /interactive federation controls/i })).toBeVisible();

  const vpnCard = page.locator(".scenario-card").filter({ hasText: /shared vpn exit across partners/i }).first();
  await expect(vpnCard).toBeVisible();
  await vpnCard.getByRole("button", { name: /activate now/i }).click();

  await expect(page.getByText(/shared vpn exit across partners accepted/i)).toBeVisible({ timeout: 20000 });
  await expect(page.getByText(/equity-bank-ke, kcb-bank-ke, safaricom-ke/i)).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: `${OUTPUT_DIR}/03b-command-network-federation.png`, fullPage: true });
});

test("agency onboarding exposes federation controls", async ({ page }) => {
  await login(page);
  await openSystemNav(page);

  await page.getByRole("button", { name: /agency onboarding/i }).click();
  await expect(page.getByRole("heading", { name: /agency onboarding/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /register federation partners/i })).toBeVisible();

  await page.getByRole("button", { name: /register federation partners/i }).click();
  await expect(page.getByText(/registered|already present/i)).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: `${OUTPUT_DIR}/03c-agency-onboarding-demo-controls.png`, fullPage: true });
});

test("reports builder loads with export controls", async ({ page }) => {
  await login(page);

  await page.locator("aside").getByRole("button", { name: /^s8 reports$/i }).click();
  await expect(page.getByText(/preview and findings/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /preview json/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /download report/i })).toBeVisible();
  await expect(page.getByText(/incident brief/i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/04-reports-preview.png`, fullPage: true });
});

test("defense screen renders the execute-action surface", async ({ page }) => {
  await login(page);

  await page.locator("aside").getByRole("button", { name: /^s6 defense$/i }).click();
  await expect(page.getByRole("heading", { name: /defense & containment/i })).toBeVisible();
  await expect(page.getByText(/execute action/i)).toBeVisible();
  await expect(page.locator("select").first()).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/05-defense.png`, fullPage: true });
});

test("live feed opens and shows event detail workflow", async ({ page }) => {
  await login(page);

  await page.locator("aside").getByRole("button", { name: /^s1 live feed$/i }).click();
  await expect(page.getByRole("heading", { name: /national live feed/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /operator queue/i })).toBeVisible();
  await expect(page.getByText(/sources · .*events/i)).toBeVisible();

  const firstQueueEvent = page.locator(".lf-section").getByRole("button").first();
  await expect(firstQueueEvent).toBeVisible({ timeout: 15000 });
  await firstQueueEvent.click();
  await expect(page.getByText("Event hash", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/06-live-feed-detail.png`, fullPage: true });
});

test("investigate screen shows analysis provenance and graph context", async ({ page }) => {
  await login(page);

  await page.locator("aside").getByRole("button", { name: /^s3 investigate$/i }).click();
  await expect(page.getByRole("heading", { name: /cyber threat analysis|fraud-chain analysis|integrity risk analysis/i })).toBeVisible();
  await page.getByPlaceholder("ip:50.16.16.211, service_id:ecitizen, account_h:…, domain:…").fill("ip:50.16.16.211");
  await page.getByRole("main").getByRole("button", { name: /^investigate$/i }).click();

  await expect(page.getByText(/ai detection rationale/i)).toBeVisible({ timeout: 20000 });
  await expect(page.getByText(/analysis sources/i)).toBeVisible();
  await expect(page.getByText(/graph, telemetry, and campaign context/i)).toBeVisible();
  await expect(page.getByText(/inference provenance/i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/06b-investigate-analysis.png`, fullPage: true });
});

test("campaigns and threat graph render from the analyst workflow", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: /s4 campaigns/i }).click();
  await expect(page.getByRole("heading", { name: /campaign console/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /generate case packet/i })).toBeVisible({ timeout: 15000 });
  await page.screenshot({ path: `${OUTPUT_DIR}/07-campaigns.png`, fullPage: true });

  await page.getByRole("button", { name: /s2 threat graph/i }).click();
  await expect(page.getByRole("heading", { name: /threat graph explorer/i })).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/08-threat-graph.png`, fullPage: true });
});

test("corruption intelligence loads from the system drawer", async ({ page }) => {
  await login(page);
  await openSystemNav(page);

  await page.getByRole("button", { name: /corruption intel/i }).click();
  await expect(page.getByRole("heading", { name: /corruption intelligence/i })).toBeVisible();
  await expect
    .poll(async () => {
      const syncing = await page.getByText(/integrity feeds are syncing/i).count();
      const leadTender = await page.getByText(/TND-KE-2026-0001/i).count();
      const integrityAlert = await page.getByText(/record_deletion/i).count();
      return syncing > 0 || leadTender > 0 || integrityAlert > 0;
    })
    .toBeTruthy();
  await page.screenshot({ path: `${OUTPUT_DIR}/09-corruption-intel.png`, fullPage: true });
});

test("reports can trigger a real download", async ({ page }) => {
  await login(page);

  await page.locator("aside").getByRole("button", { name: /^s8 reports$/i }).click();
  await expect(page.getByText(/preview and findings/i)).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /download report/i }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/\.(html|json|pdf|txt)$/i);
  await expect(page.getByText(/downloaded /i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/10-report-download.png`, fullPage: true });
});
