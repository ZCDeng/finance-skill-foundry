#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { createRequire } = require('node:module');

const repo = path.resolve(__dirname, '..');
const defaultSourceRoot = path.join(repo, 'app');
const sourceRoot = path.resolve(process.env.SOURCE_ROOT || defaultSourceRoot);
const appRequire = createRequire(path.join(defaultSourceRoot, 'package.json'));
const reportDir = path.join(sourceRoot, 'build', 'control-states');
const screenshotRoot = process.env.CONTROL_STATES_SCREENSHOT_DIR || '/tmp';

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function colorTuple(value) {
  const text = value.trim().toLowerCase();
  const hex = /^#([0-9a-f]{6})([0-9a-f]{2})?$/.exec(text);
  if (hex) {
    const raw = hex[1];
    return [
      Number.parseInt(raw.slice(0, 2), 16),
      Number.parseInt(raw.slice(2, 4), 16),
      Number.parseInt(raw.slice(4, 6), 16),
      hex[2] ? Number.parseInt(hex[2], 16) / 255 : 1,
    ];
  }
  const rgba = /^rgba?\(([^)]+)\)$/.exec(text);
  if (!rgba) return null;
  const parts = rgba[1].split(',').map((part) => Number.parseFloat(part.trim()));
  return [parts[0], parts[1], parts[2], parts[3] ?? 1];
}

function sameColor(a, b) {
  const left = colorTuple(a);
  const right = colorTuple(b);
  if (!left || !right) return a.replace(/\s+/g, '').toLowerCase() === b.replace(/\s+/g, '').toLowerCase();
  return left.every((value, index) => Math.abs(value - right[index]) <= (index === 3 ? 0.01 : 1));
}

function writeFixture() {
  ensureDir(reportDir);
  const snapshotModules = path.join(sourceRoot, 'node_modules');
  const defaultModules = path.join(defaultSourceRoot, 'node_modules');
  if (sourceRoot !== defaultSourceRoot && !fs.existsSync(path.join(snapshotModules, 'react'))) {
    if (!fs.existsSync(snapshotModules) && fs.existsSync(defaultModules)) {
      fs.symlinkSync(defaultModules, snapshotModules, 'dir');
    } else {
      throw new Error(`SOURCE_ROOT node_modules is present but cannot resolve react: ${snapshotModules}`);
    }
  }
  fs.writeFileSync(path.join(reportDir, 'fixture.html'), `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>FA control state fixture</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./fixture.tsx"></script>
  </body>
</html>
`);
  fs.copyFileSync(path.join(defaultSourceRoot, 'tests/fixtures/control-states.tsx'), path.join(reportDir, 'fixture.tsx'));
}

async function main() {
  writeFixture();
  const [{ createServer }, reactModule, tailwindModule] = await Promise.all([
    import(appRequire.resolve('vite')),
    import(appRequire.resolve('@vitejs/plugin-react')),
    import(appRequire.resolve('@tailwindcss/vite')),
  ]);
  const react = reactModule.default;
  const tailwindcss = tailwindModule.default;
  const pwPath = process.env.PLAYWRIGHT_MODULE || '/Users/zcdeng/.agents/skills/claude-design-card/node_modules/playwright-core';
  const { chromium } = require(pwPath);
  const server = await createServer({
    root: sourceRoot,
    configFile: false,
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.join(sourceRoot, 'src') } },
    server: { host: '127.0.0.1', port: 0, strictPort: false },
    logLevel: 'error',
  });
  await server.listen();
  const base = server.resolvedUrls.local[0];
  const executablePath = [
    process.env.CONTROL_STATES_BROWSER,
    chromium.executablePath().replace('chromium_headless_shell-', 'chromium-').replace('/chrome-headless-shell-mac-arm64/chrome-headless-shell', '/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ].find((candidate) => candidate && fs.existsSync(candidate));
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const page = await browser.newPage({ viewport: { width: 980, height: 760 }, deviceScaleFactor: 1 });
  const failures = [];
  const record = [];
  const screenshots = [];

  const waitTransition = () => page.waitForTimeout(240);
  const token = async (name) => page.evaluate((key) => getComputedStyle(document.documentElement).getPropertyValue(key).trim(), name);
  const color = async (value) => page.evaluate((raw) => {
    const probe = document.createElement('span');
    probe.style.color = raw;
    document.body.appendChild(probe);
    const computed = getComputedStyle(probe).color;
    probe.remove();
    return computed;
  }, value);
  const read = async (selector) => page.locator(selector).first().evaluate((node) => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return {
      label: node.getAttribute('aria-label') || node.textContent?.trim() || selector,
      borderColor: style.borderColor,
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      outlineOffset: style.outlineOffset,
      color: style.color,
      backgroundColor: style.backgroundColor,
      fontSize: style.fontSize,
      lineHeight: style.lineHeight,
      opacity: style.opacity,
      pointerEvents: style.pointerEvents,
      height: rect.height,
      width: rect.width,
      top: rect.top,
      bottom: rect.bottom,
      left: rect.left,
      right: rect.right,
    };
  });
  const tabTo = async (selector) => {
    await page.locator('body').click({ position: { x: 4, y: 4 } });
    for (let index = 0; index < 24; index += 1) {
      await page.keyboard.press('Tab');
      const reached = await page.locator(selector).first().evaluate((node) => document.activeElement === node);
      if (reached) return true;
    }
    return false;
  };
  const check = (name, ok, detail) => {
    record.push({ name, ok, detail });
    if (!ok) failures.push({ name, detail });
  };
  const shot = async (theme, name) => {
    const file = path.join(screenshotRoot, `fa-control-states-${theme}-${name}-${Date.now()}.png`);
    await page.screenshot({ path: file, fullPage: true });
    screenshots.push(file);
  };

  try {
    await page.goto(new URL('/build/control-states/fixture.html', base).toString(), { waitUntil: 'networkidle' });
    for (const theme of ['light', 'dark']) {
      await page.evaluate((nextTheme) => { document.documentElement.dataset.theme = nextTheme; }, theme);
      await waitTransition();
      const neutral = await color(await token('--fnd-line'));
      const hover = await color(await token('--fnd-line-hover'));
      const focus = await color(await token('--fnd-focus'));
      const invalid = await color(await token('--fnd-mark-outside-line'));
      const ink = await color(await token('--fnd-ink'));
      const muted = await color(await token('--fnd-muted'));
      const onAccent = await color(await token('--fnd-on-accent'));
      const accent = await color(await token('--fnd-accent'));

      const fields = [
        ['legacy input', 'input[aria-label="账簿"]'],
        ['shadcn input', 'input[aria-label="shadcn input"]'],
        ['shadcn textarea', 'textarea[aria-label="shadcn textarea"]'],
        ['period input', 'input[aria-label="期间"]'],
        ['date input', 'input[aria-label="日期"]'],
        ['decimal input', 'input[aria-label="金额"]'],
      ];
      for (const [name, selector] of fields) {
        const before = await read(selector);
        await page.hover(selector);
        await waitTransition();
        const hovered = await read(selector);
        check(`${theme} ${name} default neutral border`, sameColor(before.borderColor, neutral), { before, expected: neutral });
        check(`${theme} ${name} hover remains neutral`, sameColor(hovered.borderColor, neutral) || sameColor(hovered.borderColor, hover), { hovered, neutral, hover });
      }

      for (const [name, selector] of fields.slice(0, 3)) {
        const reachedByTab = await tabTo(selector);
        await waitTransition();
        const keyboard = await read(selector);
        check(`${theme} ${name} keyboard focus has one inset focus stroke`, reachedByTab && keyboard.outlineStyle !== 'none' && keyboard.outlineWidth === '1px' && sameColor(keyboard.outlineColor, focus) && keyboard.outlineOffset === '-1px' && sameColor(keyboard.borderColor, neutral), { reachedByTab, keyboard, neutral });

        await page.locator('body').click({ position: { x: 4, y: 4 } });
        await page.locator(selector).click();
        await waitTransition();
        const mouse = await read(selector);
        check(`${theme} ${name} mouse focus keeps neutral border`, sameColor(mouse.borderColor, neutral), { mouse, neutral });

        await page.hover(selector);
        await waitTransition();
        const hoverFocus = await read(selector);
        check(`${theme} ${name} hover+focus keeps neutral border`, sameColor(hoverFocus.borderColor, neutral), { hoverFocus, neutral, focus });
      }

      const invalidSelectors = [
        ['legacy invalid', 'input[aria-label="账簿错误"]'],
        ['shadcn invalid input', 'input[aria-label="shadcn input error"]'],
        ['shadcn invalid textarea', 'textarea[aria-label="shadcn textarea error"]'],
      ];
      for (const [name, selector] of invalidSelectors) {
        await page.hover(selector);
        await waitTransition();
        const value = await read(selector);
        check(`${theme} ${name} survives hover`, sameColor(value.borderColor, invalid), { value, expected: invalid });
      }

      const disabledSelectors = [
        ['legacy disabled input', 'input[aria-label="账簿禁用"]'],
        ['shadcn disabled input', 'input[aria-label="shadcn input disabled"]'],
        ['shadcn disabled textarea', 'textarea[aria-label="shadcn textarea disabled"]'],
        ['disabled ghost button', 'button[aria-label="disabled ghost action"]'],
      ];
      for (const [name, selector] of disabledSelectors) {
        await waitTransition();
        const value = await read(selector);
        check(`${theme} ${name} remains visibly disabled`, Number(value.opacity) < 1 || value.pointerEvents === 'none', value);
      }

      const period = await read('input[aria-label="期间"]');
      const calendar = await read('button[aria-label="期间打开年月选择"]');
      check(`${theme} calendar button contained`, calendar.height <= 26 && calendar.width <= 26 && calendar.top >= period.top && calendar.bottom <= period.bottom, { period, calendar });
      const date = await read('input[aria-label="日期"]');
      const toggle = await read('button[aria-label="日期打开日期选择"]');
      check(`${theme} date toggle contained`, toggle.top >= date.top && toggle.bottom <= date.bottom && toggle.right <= date.right + 1, { date, toggle });
      const decimal = await read('input[aria-label="金额"]');
      check(`${theme} decimal keeps field geometry`, decimal.height === 36 && sameColor(decimal.borderColor, neutral), { decimal, neutral });

      const primary = await read('button[aria-label="primary action"]');
      check(`${theme} button typography remains 14px`, primary.fontSize === '14px' && primary.lineHeight === '14px', primary);
      check(`${theme} primary button uses token colours`, sameColor(primary.color, onAccent) && sameColor(primary.backgroundColor, accent), { primary, onAccent, accent });

      for (const [name, selector] of [
        ['ghost', 'button[aria-label="ghost action"]'],
        ['link', 'button[aria-label="link action"]'],
        ['inactive tab', '[data-slot="tabs-trigger"][data-state="inactive"]'],
      ]) {
        const before = await read(selector);
        await page.hover(selector);
        await waitTransition();
        const hovered = await read(selector);
        check(`${theme} ${name} hover reaches foreground`, sameColor(before.color, muted) && sameColor(hovered.color, ink), { before, hovered, muted, ink });
      }
      await shot(theme, failures.length ? 'state' : 'pass');
    }

    const sourceFiles = [
      'src/styles/base.css',
      'src/views/analysis.css',
      'src/components/workspace.css',
      'src/components/components.css',
      'src/components/financial-controls.css',
      'src/components/ui/input.tsx',
      'src/components/ui/textarea.tsx',
      'src/components/ui/button.tsx',
      'src/components/ui/tabs.tsx',
    ].filter((rel) => fs.existsSync(path.join(sourceRoot, rel)));
    const sourceHash = createHash('sha256');
    for (const rel of sourceFiles) sourceHash.update(rel).update(fs.readFileSync(path.join(sourceRoot, rel)));
    const report = { ok: failures.length === 0, sourceRoot, sourceHash: sourceHash.digest('hex'), checked: record.length, failures, screenshots, record };
    const reportPath = path.join(reportDir, 'report.json');
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ ok: report.ok, sourceRoot, reportPath, checked: record.length, failures, screenshots }, null, 2));
    if (failures.length) process.exitCode = 1;
  } finally {
    await browser.close().catch(() => {});
    await server.close().catch(() => {});
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
