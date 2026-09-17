// Run with Playwright installed: node tests/browser.cjs [base URL]
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const base = process.argv[2] || "http://127.0.0.1:4173";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  fs.mkdirSync("qa", { recursive: true });
  try {
    const routes = [
      "/",
      "/archive/",
      "/reader/",
      "/reader/09-17/",
      "/reader/09-08/",
      "/episode/2026-09-17/",
      "/episode/2026-09-08/",
      "/about/",
      "/subscribe/",
      "/404.html",
    ];
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      for (const route of routes) {
        const response = await page.goto(base + route);
        assert.ok(
          response.status() === 200 ||
            (route === "/404.html" && response.status() === 404),
        );
        await page.evaluate(() => document.fonts.ready);
        assert.equal(
          await page.locator("h1").count(),
          1,
          route + ": exactly one h1",
        );
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
          route + ": overflow at " + width,
        );
        assert.equal(
          await page.locator('a[href=""], a[href="#"]').count(),
          0,
          route + ": placeholder links",
        );
      }
    }
    console.log(
      "PASS: 10 page types at 1440, 768, 390 and 320px; no overflow or placeholder links.",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + "/");
    await page.getByRole("button", { name: "Menu", exact: true }).click();
    assert.equal(
      await page.locator("[data-nav-toggle]").getAttribute("aria-expanded"),
      "true",
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("[data-nav-toggle]").getAttribute("aria-expanded"),
      "false",
    );
    await page.locator("[data-nav-toggle]").click();
    await page
      .locator("#primary-nav")
      .getByRole("link", { name: "Episodes", exact: true })
      .click();
    assert.equal(new URL(page.url()).pathname, "/archive/");
    const allEpisodes = await page.locator("[data-ep-card]").count();
    await page.getByRole("searchbox").fill("st lambert");
    assert.equal(await page.locator("[data-ep-card]:visible").count(), 1);
    await page.getByRole("searchbox").fill("No Such Saint");
    assert.equal(await page.locator("[data-empty]").isVisible(), true);
    await page.getByRole("button", { name: "Clear filters" }).click();
    assert.equal(
      await page.locator("[data-ep-card]:visible").count(),
      allEpisodes,
    );
    await page.goto(base + "/reader/");
    assert.equal(await page.locator(".calendar-day").count(), 366);
    await page.goto(base + "/reader/02-29/");
    await page.getByRole("link", { name: "NEXT DAY → 1 March" }).click();
    assert.equal(new URL(page.url()).pathname, "/reader/03-01/");
    const before = await page
      .locator(".reading-body")
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    await page.getByRole("button", { name: "Larger text" }).click();
    await page.reload();
    assert.equal(
      await page
        .locator(".reading-body")
        .evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
      before + 1,
    );
    console.log(
      "PASS: mobile navigation, Escape key, archive search/reset, 366 calendar links, leap day, saved text size.",
    );
    await page.goto(base + "/");
    await page
      .getByRole("button", { name: "Play reading", exact: true })
      .click();
    await page.waitForFunction(
      () => {
        const audio = document.querySelector("audio");
        return !audio.paused && audio.currentTime > 0.2;
      },
      undefined,
      { timeout: 25000 },
    );
    await page
      .getByRole("button", { name: "Pause reading", exact: true })
      .click();
    assert.equal(
      await page.locator("audio").evaluate((audio) => audio.paused),
      true,
    );
    await page.locator("[data-speed]").click();
    assert.equal(
      await page.locator("audio").evaluate((audio) => audio.playbackRate),
      1.25,
    );
    await page.locator("[data-seek]").evaluate((el) => {
      el.value = "50";
      el.dispatchEvent(new Event("input"));
    });
    const progress = await page
      .locator("audio")
      .evaluate((audio) => audio.currentTime / audio.duration);
    assert.ok(progress > 0.49 && progress < 0.51);
    await page.goto(base + "/episode/2026-09-17/");
    assert.equal(await page.locator("iframe").count(), 0);
    await page.locator(".video-launch").click();
    assert.match(
      await page.locator("iframe").getAttribute("src"),
      /youtube-nocookie.com\/embed\/7eZftC9b6Bk/,
    );
    console.log(
      "PASS: real audio playback/pause, playback speed, seeking, click-to-load video.",
    );
    const fallback = await browser.newContext({
      javaScriptEnabled: false,
      viewport: { width: 390, height: 844 },
    });
    const fallbackPage = await fallback.newPage();
    await fallbackPage.goto(base + "/");
    assert.equal(
      await fallbackPage.locator("audio[controls]").isVisible(),
      true,
    );
    assert.equal(await fallbackPage.locator("#primary-nav").isVisible(), true);
    await fallback.close();
    console.log(
      "PASS: mobile navigation and native audio available without JavaScript.",
    );
    for (const [width, label] of [
      [1440, "desktop"],
      [390, "mobile"],
    ]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const [route, name] of [
        ["/", "home"],
        ["/archive/", "archive"],
        ["/reader/09-17/", "reader"],
        ["/episode/2026-09-17/", "episode"],
      ]) {
        await page.goto(base + route);
        await page.evaluate(async () => {
          await document.fonts.ready;
          await Promise.all(
            [...document.images].map((img) => {
              img.loading = "eager";
              return img.decode().catch(() => {});
            }),
          );
        });
        assert.deepEqual(
          await page.evaluate(() =>
            [...document.images]
              .filter((img) => !img.naturalWidth)
              .map((img) => img.src),
          ),
          [],
        );
        await page.screenshot({
          path: "qa/redesign-" + name + "-" + label + ".png",
          fullPage: true,
        });
      }
    }
    assert.deepEqual(errors, []);
    console.log(
      "PASS: all visible images, desktop/mobile screenshots, no JavaScript errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
