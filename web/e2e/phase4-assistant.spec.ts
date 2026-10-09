import { expect, test, type Page } from "@playwright/test";

async function connectZoo(page: Page) {
  await page.goto("/");
  const existing = page.getByRole("link", { name: /zoo agent/i }).first();
  if (await existing.isVisible().catch(() => false)) {
    await existing.click();
    await expect(page.getByRole("tab", { name: "Chat" })).toBeVisible();
    return;
  }
  await page.getByRole("button", { name: /connect an agent/i }).first().click();
  await page.getByLabel(/agent address/i).fill("http://127.0.0.1:9898");
  await page.getByRole("button", { name: /find agent/i }).click();
  await page.getByRole("button", { name: /^connect$/i }).click();
  await expect(page.getByRole("tab", { name: "Chat" })).toBeVisible();
}

async function newChat(page: Page) {
  await page.getByRole("link", { name: "Assistant" }).first().click();
  await page.getByRole("link", { name: /new chat/i }).click();
  await page.getByLabel("Provider").selectOption("openai");
  await page.getByLabel(/^model$/i).fill("scripted");
}

test("the assistant calls an agent, answers its question and links to the conversation", async ({ page }) => {
  await connectZoo(page);
  await page.getByRole("link", { name: "Settings" }).click();
  const openai = page.getByRole("region", { name: /openai/i });
  await openai.getByLabel(/base url/i).fill("http://127.0.0.1:9897/v1");
  await openai.getByLabel(/api key/i).fill("test-key");
  await openai.getByRole("button", { name: /^save$/i }).click();
  await expect(openai.getByText(/saved ••••/i)).toBeVisible();
  await newChat(page);

  const box = page.getByPlaceholder(/ask the assistant/i);
  await box.fill("ask");
  await box.press("Enter");
  await expect(page.getByText("Done: You chose: B")).toBeVisible();
  const cards = page.getByTestId("step-card");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(1)).toContainText(/answered by the assistant/i);
  await page.getByRole("button", { name: /view llm call/i }).last().click();
  const drawer = page.getByRole("complementary", { name: "Inspect" });
  await expect(drawer.getByText("LLM call").first()).toBeVisible();
  await expect(drawer.getByText(/"model": "scripted"/).first()).toBeVisible();
  await drawer.getByRole("button", { name: /close inspect/i }).click();
  await cards.nth(1).getByRole("button").first().click();
  await cards.nth(1).getByRole("link", { name: /open this conversation/i }).click();
  await expect(page.getByText("You chose: B").first()).toBeVisible();
});

test("pass-through: the agent's question comes to you and your reply goes to the agent", async ({ page }) => {
  await connectZoo(page);
  await newChat(page);
  await page.getByRole("button", { name: /agents speak directly/i }).click();
  const box = page.getByPlaceholder(/ask the assistant/i);
  await box.fill("ask");
  await box.press("Enter");
  await expect(page.getByText(/is asking you/i)).toBeVisible();
  const reply = page.getByPlaceholder(/reply to zoo agent/i);
  await reply.fill("A");
  await reply.press("Enter");
  await expect(page.getByText("Done: You chose: A")).toBeVisible();
  await expect(page.getByTestId("step-card").last()).toContainText(/answered by you/i);
});

test("the Integrate tab shows spec-following client code", async ({ page }) => {
  await connectZoo(page);
  await page.getByRole("tab", { name: "Integrate" }).click();
  await expect(page.getByText(/async def call_agent/)).toBeVisible();
  await page.getByRole("button", { name: "OpenAI Agents SDK" }).click();
  await expect(page.getByText(/@function_tool/)).toBeVisible();
});

test("chats and conversations can be deleted", async ({ page }) => {
  await connectZoo(page);
  await page.getByRole("link", { name: "Assistant" }).first().click();
  await expect(page.getByRole("button", { name: /^delete chat/i }).first()).toBeVisible();
  const before = await page.getByRole("button", { name: /^delete chat/i }).count();
  await page.getByRole("button", { name: /^delete chat/i }).first().click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("button", { name: /^delete chat/i })).toHaveCount(before - 1);
  await page.getByRole("link", { name: /zoo agent/i }).first().click();
  await expect(page.getByRole("button", { name: /^delete conversation/i }).first()).toBeVisible();
  const convs = await page.getByRole("button", { name: /^delete conversation/i }).count();
  await page.getByRole("button", { name: /^delete conversation/i }).first().click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("button", { name: /^delete conversation/i })).toHaveCount(convs - 1);
});
