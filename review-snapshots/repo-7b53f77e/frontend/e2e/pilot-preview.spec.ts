import { expect, test } from "@playwright/test";

test.describe("V3 pilot preview", () => {
  test("renders the bounded preview-only contract", async ({ page }) => {
    await page.goto("/pilot-preview");
    await expect(page.getByText("MF-DEMO-V3-01")).toBeVisible();
    await expect(page.getByText("PREVIEW ONLY · NO FULL APPLY")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Pilot Preview · V3 seated identity" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Resolve source context" })).toBeDisabled();
  });

  test("C1 live render and download", async ({}, testInfo) => {
    testInfo.skip(true, "requires the live owner backend, source project, SAM2, and encoder runtime");
  });

  test("C1 reload preserves job", async ({}, testInfo) => {
    testInfo.skip(true, "requires a completed live pilot job");
  });

  test("C1 invalid input and cancel retry", async ({}, testInfo) => {
    testInfo.skip(true, "requires a live backend and durable cancellation race");
  });
});
