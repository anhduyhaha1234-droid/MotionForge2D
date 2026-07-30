# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: happy-path.spec.ts >> MotionForge 2D — Happy Path >> full workflow: create → select → replace → render
- Location: e2e\happy-path.spec.ts:28:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('text=Kết quả tách object')
Expected: visible
Timeout: 120000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 120000ms
  - waiting for locator('text=Kết quả tách object')

```

```yaml
- alert
- heading "Chọn vật thể" [level=2]
- text: 320×240 • 30fps • Frame 0/59
- heading "Vật thể" [level=3]
- paragraph: Chưa có vật thể nào
- heading "Công cụ chọn" [level=3]
- button "Điểm +"
- button "Điểm −"
- button "Hộp"
- button "Xóa"
- button "Xem mask"
- button "Chấp nhận & Tách"
- heading "Frame" [level=3]
- slider: "0"
- text: 0 59
- heading "Điểm đã chọn (1)" [level=3]
- text: +(59,38)
```

# Test source

```ts
  1  | import { test, expect } from "@playwright/test";
  2  | import path from "path";
  3  | import { execSync } from "child_process";
  4  | 
  5  | const FIXTURE_DIR = path.join(__dirname, "fixtures");
  6  | const VIDEO_PATH = path.join(FIXTURE_DIR, "test-2s.mp4");
  7  | 
  8  | /* ── Setup: generate a tiny test video ──────────────────────────────────── */
  9  | 
  10 | test.beforeAll(() => {
  11 |   const fs = require("fs");
  12 |   if (!fs.existsSync(FIXTURE_DIR)) fs.mkdirSync(FIXTURE_DIR, { recursive: true });
  13 |   if (!fs.existsSync(VIDEO_PATH)) {
  14 |     try {
  15 |       execSync(
  16 |         `ffmpeg -y -f lavfi -i "color=c=blue:s=320x240:d=2" -vf "drawtext=text='Test':fontsize=40:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2" -c:v libx264 -pix_fmt yuv420p "${VIDEO_PATH}"`,
  17 |         { stdio: "ignore" },
  18 |       );
  19 |     } catch {
  20 |       console.warn("ffmpeg not available — fixture video not created");
  21 |     }
  22 |   }
  23 | });
  24 | 
  25 | /* ── Happy-path E2E ─────────────────────────────────────────────────────── */
  26 | 
  27 | test.describe("MotionForge 2D — Happy Path", () => {
  28 |   test("full workflow: create → select → replace → render", async ({
  29 |     page,
  30 |   }) => {
  31 |     // Step 1: Open the app
  32 |     await page.goto("/");
  33 |     await expect(page.locator("h1")).toContainText("MotionForge 2D");
  34 | 
  35 |     // Step 2: Fill project name
  36 |     const nameInput = page.locator('input[type="text"]');
  37 |     await nameInput.clear();
  38 |     await nameInput.fill("E2E Test Project");
  39 | 
  40 |     // Step 3: Upload fixture video
  41 |     const fileInput = page.locator('input[type="file"][accept*=".mp4"]');
  42 |     await fileInput.setInputFiles(VIDEO_PATH);
  43 | 
  44 |     // Step 4: Start upload & ingest
  45 |     await page.getByRole("button", { name: /Bắt đầu/i }).click();
  46 | 
  47 |     // Step 5: Wait for ingest — app auto-navigates to selection screen
  48 |     await expect(page.locator("text=Chọn vật thể")).toBeVisible({
  49 |       timeout: 90_000,
  50 |     });
  51 | 
  52 |     // Step 6: Verify frame info is visible
  53 |     await expect(page.locator("text=320×240")).toBeVisible({ timeout: 5_000 });
  54 | 
  55 |     // Step 7: Click on canvas to select an object
  56 |     const canvas = page.locator("canvas").first();
  57 |     await expect(canvas).toBeVisible();
  58 |     await canvas.click({ position: { x: 160, y: 120 } });
  59 | 
  60 |     // Wait for selection to register
  61 |     await page.waitForTimeout(500);
  62 | 
  63 |     // Step 8: Preview mask
  64 |     const maskBtn = page.getByRole("button", { name: /Xem mask/i });
  65 |     await expect(maskBtn).toBeVisible({ timeout: 5_000 });
  66 |     await maskBtn.click();
  67 | 
  68 |     // Wait for mask to load
  69 |     await page.waitForTimeout(2000);
  70 | 
  71 |     // Step 9: Accept and propagate
  72 |     const acceptBtn = page.getByRole("button", { name: /Chấp nhận/i });
  73 |     await expect(acceptBtn).toBeVisible({ timeout: 5_000 });
  74 |     await acceptBtn.click();
  75 | 
  76 |     // Step 10: Wait for propagation to complete — Screen C
> 77 |     await expect(page.locator("text=Kết quả tách object")).toBeVisible({
     |                                                            ^ Error: expect(locator).toBeVisible() failed
  78 |       timeout: 120_000,
  79 |     });
  80 | 
  81 |     // Step 11: Verify gallery is visible
  82 |     await expect(
  83 |       page.locator("text=/Gallery frame đại diện/"),
  84 |     ).toBeVisible({ timeout: 10_000 });
  85 | 
  86 |     // Step 12: Navigate to replacement screen
  87 |     const replaceBtn = page.getByRole("button", { name: /Thay ảnh/i });
  88 |     if (await replaceBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
  89 |       await replaceBtn.click();
  90 |       await expect(page.locator("text=Thay thế vật thể")).toBeVisible({
  91 |         timeout: 5_000,
  92 |       });
  93 |     }
  94 |   });
  95 | });
  96 | 
```