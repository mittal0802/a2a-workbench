import { expect, test, type Page } from "@playwright/test";

async function connect(page: Page, address: string) {
  await page.goto("/");
  await page.getByRole("button", { name: /connect an agent/i }).first().click();
  await page.getByLabel(/agent address/i).fill(address);
  await page.getByRole("button", { name: /find agent/i }).click();
  await page.getByRole("button", { name: /^connect$/i }).click();
  await expect(page.getByRole("tab", { name: "Chat" })).toBeVisible();
}

test("sign in through the browser (authorization code + PKCE), then chat", async ({ page }) => {
  await connect(page, "http://127.0.0.1:9890");
  await expect(page.getByText(/sign-in needed/i).first()).toBeVisible();
  await page.getByRole("tab", { name: "Security" }).click();
  const card = page.locator(".card", { hasText: "Sign in through your browser" });
  await card.getByLabel("Client ID").fill("workbench-client");
  await card.getByLabel("Client secret").fill("workbench-secret");
  const popupOpened = page.waitForEvent("popup");
  await card.getByRole("button", { name: "Sign in with your browser" }).click();
  const popup = await popupOpened;
  await expect(popup.getByRole("heading", { name: "Mock IdP" })).toBeVisible();
  await popup.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByText("Signed in", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "Chat" }).click();
  const box = page.getByPlaceholder(/message/i);
  await box.fill("hello there");
  await box.press("Enter");
  await expect(page.getByText("hello there").last()).toBeVisible();
  await expect(page.locator(".progress").getByText("Done")).toBeVisible();
});

test("an API key in the query string is sent and stays masked in Inspect", async ({ page }) => {
  await connect(page, "http://127.0.0.1:9894");
  await page.getByRole("tab", { name: "Security" }).click();
  const card = page.locator(".card", { hasText: "(apiKeyQuery)" });
  await card.getByLabel("API key").fill("zoo-api-key-1234");
  await card.getByRole("button", { name: /save/i }).click();
  await expect(card.getByText("Saved", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "Chat" }).click();
  const box = page.getByPlaceholder(/message/i);
  await box.fill("echo key works");
  await box.press("Enter");
  await expect(page.locator(".progress").getByText("Done")).toBeVisible();
  await page.getByRole("button", { name: /^inspect$/i }).click();
  await page.locator(".call", { hasText: "Send message" }).first().click();
  await page.getByRole("button", { name: "Headers" }).click();
  await expect(page.getByText(/api_key=(•|%E2%80%A2)+/).first()).toBeVisible();
  await expect(page.getByText(/zoo-api-key-1234/)).toHaveCount(0);
});
