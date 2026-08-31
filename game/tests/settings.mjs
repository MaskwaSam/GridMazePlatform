import assert from "node:assert/strict";
import {
  DEFAULT_SETTINGS,
  loadSettings,
  normalizeSettings,
  saveSettings,
  SETTING_KEYS,
  SETTINGS_SCHEMA_VERSION,
  SETTINGS_STORAGE_KEY,
} from "../js/settings.js";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
}

assert.deepEqual(loadSettings(memoryStorage()), DEFAULT_SETTINGS);
assert.deepEqual(loadSettings(), DEFAULT_SETTINGS);
assert.deepEqual(loadSettings(memoryStorage({ [SETTINGS_STORAGE_KEY]: "not json" })), DEFAULT_SETTINGS);
assert.deepEqual(
  loadSettings(memoryStorage({
    [SETTINGS_STORAGE_KEY]: JSON.stringify({
      schemaVersion: SETTINGS_SCHEMA_VERSION,
      idleTour: false,
      showGrid: false,
      confirmReset: "yes",
      unknownSetting: true,
    }),
  })),
  {
    ...DEFAULT_SETTINGS,
    idleTour: false,
    showGrid: false,
  },
);

const normalized = normalizeSettings({ reduceMotion: true, clearView: true, showTrail: 0 });
assert.equal(normalized.reduceMotion, true);
assert.equal(normalized.clearView, true);
assert.equal(normalized.showTrail, DEFAULT_SETTINGS.showTrail);
assert.deepEqual(Object.keys(normalized), SETTING_KEYS);

const savedStorage = memoryStorage();
assert.equal(saveSettings({ ...DEFAULT_SETTINGS, showImpactMarkers: false }, savedStorage), true);
const encoded = JSON.parse(savedStorage.getItem(SETTINGS_STORAGE_KEY));
assert.equal(encoded.schemaVersion, SETTINGS_SCHEMA_VERSION);
assert.equal(encoded.showImpactMarkers, false);
assert.deepEqual(Object.keys(encoded).sort(), ["schemaVersion", ...SETTING_KEYS].sort());

const failingStorage = {
  getItem() { return null; },
  setItem() { throw new Error("quota"); },
};
assert.equal(saveSettings(DEFAULT_SETTINGS, failingStorage), false);
assert.equal(saveSettings(DEFAULT_SETTINGS), false);

console.log("PASS settings defaults, normalization, persistence, and storage failures");
