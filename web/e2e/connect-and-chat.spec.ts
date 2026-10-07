import { expect, test } from "@playwright/test";

test("connect the zoo agent, stream a reply, answer a question, inspect the wire", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /connect an agent/i }).first().click();
  await page.getByLabel(/agent address/i).fill("http://127.0.0.1:9898");
  await page.getByRole("button", { name: /find agent/i }).click();
  await expect(page.getByText(/signed card/i)).toBeVisible();
  await page.getByRole("button", { name: /^connect$/i }).click();

  const box = page.getByPlaceholder(/message/i);
  await box.fill("stream");
  await box.press("Enter");
  await expect(page.getByText("Streaming in four pieces.")).toBeVisible();
  await expect(page.locator(".progress").getByText("Done")).toBeVisible();

  await page.getByRole("button", { name: /^inspect$/i }).click();
  await page.getByText("Send message (stream)").first().click();
  await page.getByRole("button", { name: "Response" }).click();
  await expect(page.getByText(/event 1/)).toBeVisible();

  await box.fill("ask");
  await box.press("Enter");
  await expect(page.getByText("Which option should I pick: A or B?")).toBeVisible();
  await expect(page.getByText(/replying to the open question/i)).toBeVisible();
  await box.fill("B");
  await box.press("Enter");
  await expect(page.getByText("You chose: B")).toBeVisible();

  await page.getByRole("tab", { name: "About" }).click();
  await expect(page.getByText("Signature verified", { exact: false })).toBeVisible();
});
