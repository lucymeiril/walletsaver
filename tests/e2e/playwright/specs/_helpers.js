// @ts-check
const path = require('path');
const fs = require('fs');

const ARTIFACT_DIR = path.resolve(__dirname, '..', '..', '..', '..', '.walletsavior-live-validation', 'ui-e2e');
const SCREENSHOT_DIR = path.join(ARTIFACT_DIR, 'screenshots');
const RESULTS_FILE = path.join(ARTIFACT_DIR, 'scenarios.json');

function ensureDir(d) {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
}
ensureDir(SCREENSHOT_DIR);

function appendResult(entry) {
  ensureDir(ARTIFACT_DIR);
  let arr = [];
  if (fs.existsSync(RESULTS_FILE)) {
    try { arr = JSON.parse(fs.readFileSync(RESULTS_FILE, 'utf8')); } catch { arr = []; }
  }
  arr = arr.filter((x) => x.id !== entry.id);
  arr.push({ ...entry, recorded_at: new Date().toISOString() });
  fs.writeFileSync(RESULTS_FILE, JSON.stringify(arr, null, 2));
}

async function snap(page, id, label) {
  const safe = id.replace(/[^a-z0-9_-]/gi, '_');
  const p = path.join(SCREENSHOT_DIR, `${safe}.png`);
  await page.screenshot({ path: p, fullPage: true }).catch(() => {});
  return p;
}

module.exports = { ARTIFACT_DIR, SCREENSHOT_DIR, appendResult, snap };
