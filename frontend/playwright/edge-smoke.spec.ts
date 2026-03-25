import { expect, test, type Page } from "@playwright/test";

const OUTPUT_DIR = "test-artifacts";
const EDGE_USERNAME = process.env.E2E_EDGE_USERNAME ?? "edge_admin";
const EDGE_PASSWORD = process.env.E2E_EDGE_PASSWORD ?? "EdgeDemo2026!";
const EDGE_ENTITY = process.env.E2E_EDGE_ENTITY ?? "ip:203.0.113.8";

async function login(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /open secure login/i })).toBeVisible();
  await page.getByRole("button", { name: /open secure login/i }).click();

  await expect(page.getByText("Secure Sign-In")).toBeVisible();
  await page.getByPlaceholder("Enter your assigned username").fill(EDGE_USERNAME);
  await page.getByPlaceholder("••••••••••••").fill(EDGE_PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();

  await expect(page.getByRole("heading", { name: /national command centre/i })).toBeVisible();
}

async function openSystemNav(page: Page) {
  await page.getByRole("button", { name: /^system$/i }).click();
}

test("edge node command to federation presentation path works", async ({ page }) => {
  await login(page);

  await expect(page.getByRole("heading", { name: /national command centre/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /first moves/i })).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/11-edge-command.png`, fullPage: true });

  await page.getByRole("button", { name: /open gnn intelligence/i }).first().click();
  await expect(page.getByRole("heading", { name: /gnn intelligence hub/i })).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/12-edge-gnn.png`, fullPage: true });

  await page.locator("aside").getByRole("button", { name: /s3 investigate/i }).click();
  await expect(page.getByRole("heading", { name: /entity investigation/i })).toBeVisible();
  await page.getByPlaceholder("ip:…, account_h:…, service_id:…").fill(EDGE_ENTITY);
  await page.getByRole("main").getByRole("button", { name: /^investigate$/i }).click();
  await expect(page.getByText(`Entity: ${EDGE_ENTITY}`)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/13-edge-investigate.png`, fullPage: true });

  await openSystemNav(page);
  await page.getByRole("button", { name: /federation/i }).click();
  await expect(page.getByRole("heading", { name: /federation network/i })).toBeVisible();
  await expect(page.getByText(/local edge sync state/i)).toBeVisible();
  await expect(page.getByText(/safaricom-ke/i)).toBeVisible();
  await page.screenshot({ path: `${OUTPUT_DIR}/14-edge-federation.png`, fullPage: true });
});
