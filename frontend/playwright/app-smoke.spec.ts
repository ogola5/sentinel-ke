import { expect, test, type Page } from "@playwright/test";

const OUTPUT_DIR = "test-artifacts";

async function login(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /open secure login/i })).toBeVisible();
  await page.getByRole("button", { name: /open secure login/i }).click();

  await expect(page.getByText("Secure Sign-In")).toBeVisible();
  await page.getByPlaceholder("Enter your assigned username").fill("admin");
  await page.getByPlaceholder("••••••••••••").fill("Sentinel@Admin2025!");
  await page.getByRole("button", { name: /^sign in$/i }).click();

  await expect(page.getByRole("heading", { name: /national command centre/i })).toBeVisible();
}

async function openSystemNav(page: Page) {
  await page.getByRole("button", { name: /^system$/i }).click();
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

test("reports preview generates and renders summary content", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: /reports/i }).click();
  await expect(page.getByText(/preview and findings/i)).toBeVisible();
  await page.getByRole("button", { name: /preview json/i }).click();
  await expect(page.getByText(/preview generated\./i)).toBeVisible();
  await expect(page.getByText(/plain-english summary/i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/04-reports-preview.png`, fullPage: true });
});

test("defense screen renders the execute-action surface", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: /defense/i }).click();
  await expect(page.getByRole("heading", { name: /defense & containment/i })).toBeVisible();
  await expect(page.getByText(/execute action/i)).toBeVisible();
  await expect(page.locator("select").first()).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/05-defense.png`, fullPage: true });
});

test("live feed opens and shows event detail workflow", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: /live feed/i }).click();
  await expect(page.getByRole("heading", { name: /national live feed/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /incoming events/i })).toBeVisible();

  const eventCards = page.locator(".event-card");
  await expect(eventCards.first()).toBeVisible();
  await eventCards.first().click();
  await expect(page.getByText("Event hash", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/06-live-feed-detail.png`, fullPage: true });
});

test("campaigns and threat graph render from the analyst workflow", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: /s4 campaigns/i }).click();
  await expect(page.getByRole("heading", { name: /campaign console/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /generate case packet/i })).toBeVisible();
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
  await expect(page.getByText(/integrity pressure/i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/09-corruption-intel.png`, fullPage: true });
});

test("reports can trigger a real download", async ({ page }) => {
  await login(page);

  await page.getByRole("button", { name: /reports/i }).click();
  await expect(page.getByText(/preview and findings/i)).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /download report/i }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toMatch(/\.(html|json|pdf|txt)$/i);
  await expect(page.getByText(/downloaded /i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/10-report-download.png`, fullPage: true });
});
