import { expect, test, type Page } from "@playwright/test";

async function connect(page: Page) {
  await page.goto("/");
  const existing = page.getByRole("link", { name: /zoo agent/i }).first();
  const known = await existing.waitFor({ state: "visible", timeout: 5000 }).then(() => true, () => false);
  if (known) {
    await existing.click();
    return;
  }
  await page.getByRole("button", { name: /connect an agent/i }).first().click();
  await page.getByLabel(/agent address/i).fill("http://127.0.0.1:9898");
  await page.getByRole("button", { name: /find agent/i }).click();
  await page.getByRole("button", { name: /^connect$/i }).click();
  await expect(page.getByRole("tab", { name: "Chat" })).toBeVisible();
}

test("chat over gRPC", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: /connection settings/i }).click();
  await page.getByRole("button", { name: /^gRPC/ }).click();
  await expect(page.getByRole("button", { name: /connection settings/i })).toContainText("gRPC");
  await page.getByRole("button", { name: /new conversation/i }).click();
  const box = page.getByPlaceholder(/message/i);
  await box.fill("stream");
  await box.press("Enter");
  await expect(page.getByText("Streaming in four pieces.")).toBeVisible();
});

test("dropped stream, then resubscribe gets back in sync", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: /new conversation/i }).click();
  await page.getByRole("button", { name: /options/i }).click();
  await page.locator("label.choice", { hasText: "Flaky stream" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByText(/network conditions: flaky stream/i)).toBeVisible();
  const box = page.getByPlaceholder(/message/i);
  await box.fill("long");
  await box.press("Enter");
  await expect(page.getByText(/connection lost while the agent was/i)).toBeVisible();
  await page.getByRole("button", { name: /turn off/i }).click();
  await page.getByRole("button", { name: /resubscribe/i }).click();
  await expect(page.getByText(/back in sync/i)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/current task arrived first/i)).toBeVisible();
  await page.getByRole("button", { name: /^inspect$/i }).click();
  await expect(page.getByText(/injected: drop_stream/)).toBeVisible();
});

test("tasks tab lists completed tasks", async ({ page }) => {
  await connect(page);
  await page.getByRole("button", { name: /new conversation/i }).click();
  const box = page.getByPlaceholder(/message/i);
  await box.fill("echo for the tasks tab");
  await box.press("Enter");
  await expect(page.getByText("echo for the tasks tab").nth(1)).toBeVisible();
  await page.getByRole("tab", { name: "Tasks" }).click();
  await expect(page.getByRole("cell", { name: /echo for the tasks tab/ })).toBeVisible();
});
