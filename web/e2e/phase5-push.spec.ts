import { expect, test, type Page } from "@playwright/test";

async function openZoo(page: Page) {
  await page.goto("/");
  const existing = page.getByRole("link", { name: /zoo agent/i }).first();
  if (await existing.isVisible().catch(() => false)) {
    await existing.click();
  } else {
    await page.getByRole("button", { name: /connect an agent/i }).first().click();
    await page.getByLabel(/agent address/i).fill("http://127.0.0.1:9898");
    await page.getByRole("button", { name: /find agent/i }).click();
    await page.getByRole("button", { name: /^connect$/i }).click();
  }
  await expect(page.getByRole("tab", { name: "Chat" })).toBeVisible();
}

test("push notifications arrive in the chat and the Notifications inbox", async ({ page }) => {
  await openZoo(page);
  await page.getByRole("button", { name: /new conversation/i }).first().click();
  await page.getByRole("button", { name: /options/i }).click();
  await page.getByRole("switch", { name: /notify me by webhook/i }).click();
  await page.keyboard.press("Escape");
  const box = page.getByPlaceholder(/message/i);
  await box.fill("long");
  await box.press("Enter");
  await expect(page.getByText(/Notification ·/).first()).toBeVisible({ timeout: 15000 });
  await page.getByRole("tab", { name: "Notifications" }).click();
  await expect(page.getByText("Accepted").first()).toBeVisible();
});

test("a Workbench webhook config can be created and deleted for a task", async ({ page }) => {
  await openZoo(page);
  await page.getByRole("button", { name: /new conversation/i }).first().click();
  await page.getByRole("button", { name: /options/i }).click();
  await page.getByRole("switch", { name: /return immediately/i }).click();
  await page.keyboard.press("Escape");
  const box = page.getByPlaceholder(/message/i);
  await box.fill("slow 30");
  await box.press("Enter");
  await page.getByRole("tab", { name: "Notifications" }).click();
  const taskSelect = page.getByRole("combobox", { name: "Task" });
  const working = taskSelect.locator("option", { hasText: "Working" }).first();
  await expect(working).toBeAttached();
  await taskSelect.selectOption((await working.getAttribute("value"))!);
  await page.getByRole("button", { name: /create config/i }).click();
  const del = page.getByRole("button", { name: /^delete config/i });
  await expect(del).toHaveCount(1);
  await del.click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText(/no configs for this task yet/i)).toBeVisible();
});
