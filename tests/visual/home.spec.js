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
