// Visual regression for the main UI. The header and layout shell are static
// and render without a Home Assistant backend; the data panels are not, so
// they are masked. A dependency bump that changes the rendered styling (e.g. a
// Tailwind minor altering generated CSS) shifts the screenshot and fails here.
const { test, expect } = require("@playwright/test");

test("home page shell renders with expected styling", async ({ page }) => {
  await page.goto("/");

  // Static, data-independent anchor — must be visible before we snapshot.
  await expect(page.locator("header.desktop-header")).toBeVisible();

  // Let fonts and layout settle (data fetches fail without HA — that's fine).
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1000);

  await expect(page).toHaveScreenshot("home.png", {
    fullPage: true,
    // Data-dependent regions are empty/error without a backend → mask them.
    mask: [page.locator(".panel-container")],
  });
});

test("batch rename keeps drafts while the selection expands", async ({ page }) => {
  await page.goto("/");

  const rows = await page.evaluate(async () => {
    const app = entityManager();
    app.hierarchy = {
      areas: [
        { id: "kitchen", name: "Kitchen" },
        { id: "office", name: "Office" },
      ],
      devices: [
        { id: "light", area_id: "kitchen", name: "Kitchen Light", base_name: "Light" },
        { id: "plug", area_id: "office", name: "Office Plug", base_name: "Plug" },
        { id: "sensor", area_id: "office", name: "Office Sensor", base_name: "Sensor" },
      ],
      entities: [],
    };
    app.refreshBatchRenamePreviews = async () => {};

    app.batchRename.selected = ["light", "plug"];
    await app.openBatchRenameReview();
    app.batchRename.rows.find((row) => row.device_id === "light").base_name = "Ceil";
    app.batchRename.rows.find((row) => row.device_id === "plug").base_name = "Desk";
    app.rememberBatchRenameDraft("light", "Ceil");
    app.rememberBatchRenameDraft("plug", "Desk");
    app.closeBatchRenameReview();

    app.batchRename.selected.push("sensor");
    await app.openBatchRenameReview();
    return app.batchRename.rows.map((row) => [row.device_id, row.base_name]);
  });

  expect(rows).toEqual([
    ["light", "Ceil"],
    ["plug", "Desk"],
    ["sensor", "Sensor"],
  ]);
});

test("batch rename selects and unselects multiple areas independently", async ({ page }) => {
  await page.goto("/");

  const state = await page.evaluate(() => {
    const app = entityManager();
    app.hierarchy.devices = [
      { id: "kitchen-light", area_id: "kitchen" },
      { id: "kitchen-plug", area_id: "kitchen" },
      { id: "office-light", area_id: "office" },
      { id: "office-disabled", area_id: "office", disabled_by: "user" },
    ];

    app.toggleBatchAreaDevices("kitchen");
    app.toggleBatchAreaDevices("office");
    const selectedAcrossAreas = [...app.batchRename.selected];
    const areaCount = app.batchRenameAreaCount;
    app.toggleBatchAreaDevices("kitchen");

    return {
      selectedAcrossAreas,
      areaCount,
      selectedAfterKitchenRemoved: app.batchRename.selected,
    };
  });

  expect(state.selectedAcrossAreas).toEqual([
    "kitchen-light",
    "kitchen-plug",
    "office-light",
  ]);
  expect(state.areaCount).toBe(2);
  expect(state.selectedAfterKitchenRemoved).toEqual(["office-light"]);
});

test("batch preview keeps expanded rows stable while recalculating", async ({ page }) => {
  await page.goto("/");

  const result = await page.evaluate(async () => {
    const app = entityManager();
    app.namingConfig = { templates: {} };
    app.hierarchy = {
      floors: [],
      areas: [],
      devices: [{ id: "light", name: "Old Light", base_name: "Light", area_id: null }],
      entities: [{
        id: "light.old_light",
        registry_id: "registry-light",
        device_id: "light",
        original_name: "Light",
        user_name: null,
      }],
    };
    app.deviceNamingContext = () => ({});
    app.entityNamingContext = () => ({ entity: "Light" });

    const previousChanges = [{ old_id: "light.old_light", new_id: "light.preview" }];
    app.batchRename.rows = [{
      device_id: "light",
      current_name: "Old Light",
      base_name: "New Light",
      new_name: "Old Light",
      planned_entities: previousChanges,
      entity_changes: previousChanges,
      conflicts: [],
      has_changes: true,
      preview_open: true,
    }];

    let finishRequest;
    window.fetch = () => new Promise((resolve) => { finishRequest = resolve; });
    const refresh = app.refreshBatchRenamePreviews();
    await Promise.resolve();
    const whilePending = {
      sameChanges: app.batchRename.rows[0].entity_changes === previousChanges,
      previewOpen: app.batchRename.rows[0].preview_open,
    };

    finishRequest({
      ok: true,
      json: async () => ({ rendered: [
        { device_name: "New Light" },
        { entity_id: "light.new_light", entity_name: "Light" },
      ] }),
    });
    await refresh;

    return {
      whilePending,
      after: {
        sameChanges: app.batchRename.rows[0].entity_changes === previousChanges,
        previewOpen: app.batchRename.rows[0].preview_open,
        newName: app.batchRename.rows[0].new_name,
        previewing: app.batchRename.previewing,
      },
    };
  });

  expect(result.whilePending).toEqual({ sameChanges: true, previewOpen: true });
  expect(result.after).toEqual({
    sameChanges: false,
    previewOpen: true,
    newName: "New Light",
    previewing: false,
  });
});
