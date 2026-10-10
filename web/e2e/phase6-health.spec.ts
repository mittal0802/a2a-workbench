import { expect, test } from "@playwright/test";

test("a health check from the Health tab shows the score and a finding with its evidence", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /connect an agent/i }).first().click();
  await page.getByLabel(/agent address/i).fill("http://127.0.0.1:9886");
  await page.getByRole("button", { name: /find agent/i }).click();
  await page.getByRole("button", { name: /^connect$/i }).click();
  await page.getByRole("tab", { name: "Health" }).click();
  await expect(page.getByText(/create tasks, cancel the tasks they created/)).toBeVisible();

  const areas = page.getByRole("group", { name: "Areas" });
  await expect(areas.getByRole("button").first()).toBeVisible();
  for (const chip of await areas.getByRole("button").all()) {
    const label = (await chip.textContent()) ?? "";
    if (!label.startsWith("F ")) await chip.click();
  }
  await page.getByRole("button", { name: "Check health" }).click();

  const issue = page.getByTestId("issue-F2.get_unknown");
  await expect(issue).toBeVisible({ timeout: 20000 });
  await expect(issue).toContainText("A2A §3.1.3 · MUST");
  await expect(page.getByTestId("score")).not.toHaveText("–");
  await issue.getByRole("button", { name: "See evidence" }).click();
  await expect(page.getByTestId("evidence")).toContainText("GetTask");

  await page.getByRole("link", { name: "Health checks" }).click();
  await expect(page.getByRole("heading", { name: "Health checks" })).toBeVisible();
  await expect(page.getByText(/1 failed/)).toBeVisible();
});
