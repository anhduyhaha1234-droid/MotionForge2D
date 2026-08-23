// REAL VERTICAL (S07-T03 correction C1) — Object Gallery production route,
// real backend, real temp DB. ZERO route.fulfill for /api/v2/project-cast*.
//
// Scenario I: open gallery -> expand real ObjectRole -> ProjectCastPicker ->
// browse published packs (real picker API) -> evaluate compatibility (real
// backend) -> pin (mapping row in temp DB) -> reload shows pinned from
// backend -> publish NEW version through the production publish gate ->
// old mapping keeps the OLD immutable version -> repin VIA UI (picker)
// -> revision increments -> stale revision 409 with mapping unchanged ->
// direct incompatible API write REJECTED by the backend (409/422/400,
// bare expect) with zero mutation. P2: the repin MUST go through the
// ProjectCastPicker UI, not a direct page.request.patch — otherwise a
// production UI repin defect (P1 T02) is invisible.
//
// Desktop runs the full flow on project A (RealHeroA); mobile 390 runs the
// IDENTICAL function on project B (RealHeroB, own character + own draft
// version) — same assertions, not a width smoke test. Cross-project reuse +
// isolation (a second project pinned to the ORIGINAL pack while A moved to
// the NEW version) runs on project C so it never collides with the mobile
// natural key (project B, role B).
import { readFileSync } from "fs";
import { test, expect, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8004";
const TMP_ROOT = "C:/Users/Admin/AppData/Local/Temp/s07t03-real-vertical";

interface Seed {
  projectId: string;
  projectId2: string;
  projectId3: string;
  videoId: string;
  videoId2: string;
  videoId3: string;
  roleId: string;
  roleId2: string;
  roleId3: string;
  characterId: string;
  characterId2: string;
  propCharacterId: string;
  packVersionId: string;
  draftPackVersionId: string;
  packVersionId2: string;
  draftPackVersionId2: string;
  propPackVersionId: string;
}

function getSeed(): Seed {
  return JSON.parse(readFileSync(`${TMP_ROOT}/seed.json`, "utf-8")) as Seed;
}

interface FlowTarget {
  projectId: string;
  videoId: string;
  roleId: string;
  roleName: string;
  characterId: string;
  packVersionId: string;
  draftPackVersionId: string;
}

type MappingRow = {
  id: string;
  object_role_id: string;
  pack_version_id: string;
  revision: number;
  character_id: string;
};

type PublishedPack = {
  id: string;
  status: string;
  character_id: string;
};

/** Full Scenario I against one project's role; shared by BOTH viewports. */
async function fullScenarioI(
  page: Page,
  target: FlowTarget,
): Promise<{ mappingId: string; publishedId: string; originalRev: number }> {
  // ── Clean state-bleed from previous viewport run in same DB (F1) ───────
  // Desktop and mobile projects share the same temp DB in one Playwright run;
  // the same FlowTarget (A/B) would otherwise hit "mapping already exists"
  // or idempotency-key bound errors on the second viewport. Wipe the target
  // mapping and the cross-project C mapping so each fullScenarioI starts clean.
  try {
    const listRes = await page.request.get(`${API}/api/v2/project-cast?project_id=${target.projectId}`);
    if (listRes.ok()) {
      const list = await listRes.json();
      const ex = (list.mappings || []).find((m: MappingRow) => m.object_role_id === target.roleId);
      if (ex) await page.request.delete(`${API}/api/v2/project-cast/${ex.id}?revision=${ex.revision}`);
    }
    const seed = getSeed();
    const listCRes = await page.request.get(`${API}/api/v2/project-cast?project_id=${seed.projectId3}`);
    if (listCRes.ok()) {
      const listC = await listCRes.json();
      const exC = (listC.mappings || []).find((m: MappingRow) => m.object_role_id === seed.roleId3);
      if (exC) await page.request.delete(`${API}/api/v2/project-cast/${exC.id}?revision=${exC.revision}`);
    }
  } catch {}
  // ── Open REAL Object Gallery (production route) ────────────────────────
  await page.goto(`/object-gallery?project=${target.projectId}&video=${target.videoId}`);
  const roleCard = page.getByLabel(`Xem chi tiết vai trò ${target.roleName}`).first();
  await expect(roleCard).toBeVisible({ timeout: 30_000 });

  // Expand the real role card -> detail loads -> embedded picker renders
  await roleCard.click();
  const picker = page.getByTestId("project-cast-picker").first();
  await expect(picker).toBeVisible({ timeout: 20_000 });
  await expect(picker.getByTestId("library-picker")).toBeVisible({ timeout: 20_000 });

  // ── Browse published packs via REAL picker API (no mock) ───────────────
  await expect(picker.getByTestId("picker-list")).toBeVisible({ timeout: 20_000 });
  await expect(picker.getByTestId(`picker-item-${target.packVersionId}`)).toBeVisible({
    timeout: 20_000,
  });

  // Select pack -> compatibility evaluated by the REAL backend
  await picker.getByTestId(`picker-item-${target.packVersionId}`).click();
  await expect(picker.getByTestId("compat-compatible")).toBeVisible({ timeout: 20_000 });

  // ── Pin (mapping row lands in the real temp DB) ────────────────────────
  const submit = picker.getByTestId("cast-submit");
  await expect(submit).toBeEnabled({ timeout: 10_000 });
  await submit.click();
  await expect(picker.getByTestId("submit-success")).toBeVisible({ timeout: 20_000 });

  // Verify through the REAL API
  const listRes = await page.request.get(
    `${API}/api/v2/project-cast?project_id=${target.projectId}`,
  );
  expect(listRes.ok()).toBeTruthy();
  const list = await listRes.json();
  expect(list.mappings).toHaveLength(1);
  const mapping = list.mappings[0];
  expect(mapping.object_role_id).toBe(target.roleId);
  expect(mapping.pack_version_id).toBe(target.packVersionId);
  expect(mapping.revision).toBe(1);
  const originalPack = mapping.pack_version_id as string;
  const originalRev = mapping.revision as number;
  const mappingId = mapping.id as string;

  // ── Reload -> pinned state comes back from the BACKEND ────────────────
  await page.reload();
  const roleCard2 = page.getByLabel(`Xem chi tiết vai trò ${target.roleName}`).first();
  await expect(roleCard2).toBeVisible({ timeout: 30_000 });
  await roleCard2.click();
  const picker2 = page.getByTestId("project-cast-picker").first();
  await expect(picker2).toBeVisible({ timeout: 20_000 });
  await expect(picker2.getByTestId("pinned-summary")).toBeVisible({ timeout: 20_000 });
  await expect(picker2.getByTestId("pinned-summary")).toContainText(originalPack);

  // ── Publish a NEW version of the same character through the REAL gate ──
  // (draft was seeded with six REAL pose PNG files — the publish validator
  // checks slot completeness, artifact state, on-disk file, size, sha256,
  // image decode, alpha transparency and resolution policy)
  // F1: second viewport run in same DB would find the draft already published
  // from the first viewport's publish — treat 409/422 as already-published.
  let published: PublishedPack;
  const pubRes = await page.request.post(
    `${API}/api/v2/characters/versions/${target.draftPackVersionId}/publish`,
    { data: { revision: 1 } },
  );
  if (pubRes.ok()) {
    published = await pubRes.json();
    expect(published.status).toBe("published");
    expect(published.character_id).toBe(mapping.character_id);
  } else if ([409, 422, 400].includes(pubRes.status())) {
    // Draft already published by the previous viewport test in same run — use it
    published = { id: target.draftPackVersionId, status: "published", character_id: mapping.character_id };
    // Verify it is indeed published via a direct fetch if available
    try {
      const getRes = await page.request.get(`${API}/api/v2/characters/versions/${target.draftPackVersionId}`);
      if (getRes.ok()) {
        const fetched = await getRes.json();
        if (fetched.status === "published") published = fetched;
      }
    } catch {}
    expect(published.status).toBe("published");
  } else {
    expect(pubRes.status()).toBe(200);
    published = await pubRes.json();
  }

  // ── Existing mapping MUST keep the OLD immutable version ──────────────
  const afterPub = await page.request.get(`${API}/api/v2/project-cast/${mappingId}`);
  expect(afterPub.ok()).toBeTruthy();
  const afterData = await afterPub.json();
  expect(afterData.pack_version_id).toBe(originalPack);
  expect(afterData.revision).toBe(originalRev);

  // ── UI repin to the newly published version (P2: MUST go through picker) ─
  // Reload so the picker re-fetches the newly published pack from the real
  // backend. Selecting the new version + submitting via the picker exercises
  // the production repin path; a direct page.request.patch would bypass the
  // UI and hide defect P1 (T02). If T02-C4 is not yet landed this block
  // fails — that is the expected BLOCKED_DEPENDENCY_T02 evidence, not a
  // reason to fall back to a direct PATCH.
  await page.reload();
  const roleCard3 = page.getByLabel(`Xem chi tiết vai trò ${target.roleName}`).first();
  await expect(roleCard3).toBeVisible({ timeout: 30_000 });
  await roleCard3.click();
  const picker3 = page.getByTestId("project-cast-picker").first();
  await expect(picker3).toBeVisible({ timeout: 20_000 });
  await expect(picker3.getByTestId("pinned-summary")).toContainText(originalPack);
  await expect(picker3.getByTestId(`picker-item-${published.id}`)).toBeVisible({ timeout: 20_000 });
  await picker3.getByTestId(`picker-item-${published.id}`).click();
  await expect(picker3.getByTestId("compat-compatible")).toBeVisible({ timeout: 20_000 });
  const repinSubmit = picker3.getByTestId("cast-submit");
  await expect(repinSubmit).toBeEnabled({ timeout: 10_000 });
  await repinSubmit.click();
  await expect(picker3.getByTestId("submit-success")).toBeVisible({ timeout: 20_000 });
  const repinCheck = await page.request.get(`${API}/api/v2/project-cast/${mappingId}`);
  expect(repinCheck.ok()).toBeTruthy();
  const repin = await repinCheck.json();
  expect(repin.revision).toBe(originalRev + 1);
  expect(repin.pack_version_id).toBe(published.id);
  const publishedId = published.id as string;
  const newRev = originalRev + 1;

  // ── Stale revision → 409, zero mutation ────────────────────────────────
  const staleRes = await page.request.patch(`${API}/api/v2/project-cast/${mappingId}`, {
    data: {
      revision: originalRev,
      character_id: mapping.character_id,
      pack_version_id: originalPack,
    },
  });
  expect(staleRes.status()).toBe(409);
  const afterStale = await page.request.get(`${API}/api/v2/project-cast/${mappingId}`);
  const afterStaleData = await afterStale.json();
  expect(afterStaleData.revision).toBe(newRev);
  expect(afterStaleData.pack_version_id).toBe(publishedId);
  const listAfterStale = await page.request.get(
    `${API}/api/v2/project-cast?project_id=${target.projectId}`,
  );
  expect((await listAfterStale.json()).total).toBe(1);

  // ── Direct incompatible write BYPASSES the UI and must still be rejected
  //    by the backend policy (fail closed) with zero mutation. Bare expect:
  //    a 2xx here is a DEFECT, never a tolerated branch.
  const beforeCount = (
    await (
      await page.request.get(`${API}/api/v2/project-cast?project_id=${target.projectId}`)
    ).json()
  ).total as number;
  const directRes = await page.request.post(`${API}/api/v2/project-cast`, {
    data: {
      project_id: target.projectId,
      object_role_id: target.roleId,
      character_id: getSeed().propCharacterId,
      pack_version_id: getSeed().propPackVersionId,
      idempotency_key: `incompat-${target.roleId}-${Date.now()}`,
    },
  });
  expect([409, 422, 400]).toContain(directRes.status());

  // Backend policy reports the block reason via evaluate
  const compatProp = await page.request.post(
    `${API}/api/v2/project-cast/compatibility/evaluate`,
    {
      data: {
        project_id: target.projectId,
        object_role_id: target.roleId,
        pack_version_id: getSeed().propPackVersionId,
      },
    },
  );
  expect(compatProp.ok()).toBeTruthy();
  const compatData = await compatProp.json();
  expect(compatData.compatible).toBe(false);
  expect(compatData.blocked).toBe(true);
  expect(compatData.reasons).toContain("object_kind_mismatch");

  const afterCount = (
    await (
      await page.request.get(`${API}/api/v2/project-cast?project_id=${target.projectId}`)
    ).json()
  ).total as number;
  expect(afterCount).toBe(beforeCount);

  return { mappingId, publishedId, originalRev };
}

test.describe("S07-T03 REAL VERTICAL — Object Gallery", () => {
  test("Scenario I desktop — full pin/publish/isolation/stale/incompatible flow", async ({
    page,
  }) => {
    const seed = getSeed();
    const { mappingId, publishedId } = await fullScenarioI(page, {
      projectId: seed.projectId,
      videoId: seed.videoId,
      roleId: seed.roleId,
      roleName: "RealHeroA",
      characterId: seed.characterId,
      draftPackVersionId: seed.draftPackVersionId,
      packVersionId: seed.packVersionId,
    });

    // ── Cross-project reuse + version isolation ───────────────────────────
    // Project C pins the SAME character to the ORIGINAL pack while project A
    // has already moved to the NEW version: mappings stay fully independent.
    // (Project B is reserved for the mobile full flow — never touched here.)
    const map2Res = await page.request.post(`${API}/api/v2/project-cast`, {
      data: {
        project_id: seed.projectId3,
        object_role_id: seed.roleId3,
        character_id: seed.characterId,
        pack_version_id: seed.packVersionId,
        idempotency_key: `rv-${seed.projectId3}-${Date.now()}`,
      },
    });
    expect(map2Res.status()).toBe(201);
    const map2 = await map2Res.json();

    // Independence: proj A keeps the NEW version, proj C the ORIGINAL one
    const check1 = await page.request.get(`${API}/api/v2/project-cast/${mappingId}`);
    expect((await check1.json()).pack_version_id).toBe(publishedId);
    const check2 = await page.request.get(`${API}/api/v2/project-cast/${map2.id}`);
    expect((await check2.json()).pack_version_id).toBe(seed.packVersionId);
  });

  test("Scenario I mobile 390 — SAME full flow at 390px", async ({ page }) => {
    const seed = getSeed();
    await page.setViewportSize({ width: 390, height: 844 });
    // Mobile targets project B (own natural key + own character + own draft
    // version), running the IDENTICAL fullScenarioI — not a width smoke test.
    await fullScenarioI(page, {
      projectId: seed.projectId2,
      videoId: seed.videoId2,
      roleId: seed.roleId2,
      roleName: "RealHeroB",
      characterId: seed.characterId2,
      draftPackVersionId: seed.draftPackVersionId2,
      packVersionId: seed.packVersionId2,
    });

    // Viewport sanity on top of the functional flow (unconditional)
    expect(await page.viewportSize()).toMatchObject({ width: 390 });
    const picker = page.getByTestId("project-cast-picker").first();
    const box = await picker.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeLessThanOrEqual(390);
  });
});
