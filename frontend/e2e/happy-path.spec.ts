import { test, expect } from "@playwright/test";
import path from "path";
import { execSync } from "child_process";

const FIXTURE_DIR = path.join(__dirname, "fixtures");
const VIDEO_PATH = path.join(FIXTURE_DIR, "test-2s.mp4");

/* ── Setup: generate a tiny test video ──────────────────────────────────── */

test.beforeAll(() => {
  const fs = require("fs");
  if (!fs.existsSync(FIXTURE_DIR)) fs.mkdirSync(FIXTURE_DIR, { recursive: true });
  if (!fs.existsSync(VIDEO_PATH)) {
    try {
      execSync(
        `ffmpeg -y -f lavfi -i "color=c=blue:s=320x240:d=2" -vf "drawtext=text='Test':fontsize=40:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2" -c:v libx264 -pix_fmt yuv420p "${VIDEO_PATH}"`,
        { stdio: "ignore" },
      );
    } catch {
      console.warn("ffmpeg not available — fixture video not created");
    }
  }
});

/* ── Happy-path E2E ─────────────────────────────────────────────────────── */

test.describe("MotionForge 2D — Happy Path", () => {
  test("full workflow: create → select → replace → render", async ({
    page,
  }) => {
    // Step 1: Open the app
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("MotionForge 2D");

    // Step 2: Fill project name
    const nameInput = page.locator('input[type="text"]');
    await nameInput.clear();
    await nameInput.fill("E2E Test Project");

    // Step 3: Upload fixture video
    const fileInput = page.locator('input[type="file"][accept*=".mp4"]');
    await fileInput.setInputFiles(VIDEO_PATH);

    // Step 4: Start upload & ingest
    await page.getByRole("button", { name: /Bắt đầu/i }).click();

    // Step 5: Wait for ingest completion
    await expect(page.locator("text=Hoàn tất!")).toBeVisible({
      timeout: 90_000,
    });

    // Step 6: Should auto-navigate to selection screen
    await expect(page.locator("text=Chọn vật thể")).toBeVisible({
      timeout: 10_000,
    });

    // Step 7: Click on canvas to select an object
    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible();
    await canvas.click({ position: { x: 160, y: 120 } });

    // Step 8: Preview mask
    await page
      .getByRole("button", { name: /Xem mask/i })
      .click({ timeout: 5_000 });

    // Wait for mask preview to appear
    await expect(page.locator("canvas")).toBeVisible();

    // Step 9: Accept and propagate
    await page
      .getByRole("button", { name: /Chấp nhận/i })
      .click({ timeout: 5_000 });

    // Step 10: Wait for propagation to complete
    await expect(page.locator("text=Kết quả tách object")).toBeVisible({
      timeout: 90_000,
    });

    // Step 11: View gallery
    await expect(
      page.locator("text=Gallery frame đại diện"),
    ).toBeVisible({ timeout: 5_000 });

    // Step 12: Navigate to replacement screen
    await page
      .getByRole("button", { name: /Thay ảnh/i })
      .click({ timeout: 5_000 });

    await expect(page.locator("text=Thay thế vật thể")).toBeVisible();

    // Step 13: Upload replacement PNG
    // Generate a tiny replacement PNG if needed
    const repPath = path.join(FIXTURE_DIR, "replacement.png");
    const fs = require("fs");
    if (!fs.existsSync(repPath)) {
      try {
        execSync(
          `ffmpeg -y -f lavfi -i "color=c=red:s=64x64:d=1" -frames:v 1 "${repPath}"`,
          { stdio: "ignore" },
        );
      } catch {
        // skip if ffmpeg unavailable
      }
    }
    if (fs.existsSync(repPath)) {
      const repInput = page.locator('[data-testid="replacement-upload"]');
      await repInput.setInputFiles(repPath);
      await expect(
        page.locator('[data-testid="replacement-preview"]'),
      ).toBeVisible({ timeout: 10_000 });
    }

    // Step 14: Adjust scale slider
    const scaleSlider = page
      .locator('input[type="range"]')
      .filter({ has: page.locator("text=Tỷ lệ") })
      .first();
    // Use the 4th range slider (after anchor X, anchor Y, offset X, offset Y)
    const sliders = page.locator('input[type="range"]');
    const scaleSliderAlt = sliders.nth(4); // scale is 5th slider (0-indexed)
    if (await scaleSliderAlt.isVisible()) {
      await scaleSliderAlt.fill("1.5");
    }

    // Step 15: Verify preview updates (canvas should be present)
    await expect(
      page.locator('[data-testid="composite-canvas"]'),
    ).toBeVisible();

    // Step 16: Navigate to render screen
    await page.locator('[data-testid="next-render"]').click();
    await expect(page.locator("text=Preview & Render")).toBeVisible();
  });
});
