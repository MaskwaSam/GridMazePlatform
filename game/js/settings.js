export const SETTINGS_STORAGE_KEY = "maskwa-maze-lab-settings-v1";
export const SETTINGS_SCHEMA_VERSION = 1;

export const DEFAULT_SETTINGS = Object.freeze({
  idleTour: true,
  reduceMotion: false,
  clearView: false,
  showTrail: true,
  showImpactMarkers: true,
  showGrid: true,
  confirmReset: false,
  controllerEnabled: false,
});

export const SETTING_KEYS = Object.freeze(Object.keys(DEFAULT_SETTINGS));

export function normalizeSettings(value) {
  const source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  return Object.fromEntries(SETTING_KEYS.map((key) => [
    key,
    typeof source[key] === "boolean" ? source[key] : DEFAULT_SETTINGS[key],
  ]));
}

export function loadSettings(storage) {
  try {
    const activeStorage = storage || window.localStorage;
    const parsed = JSON.parse(activeStorage.getItem(SETTINGS_STORAGE_KEY));
    if (!parsed || parsed.schemaVersion !== SETTINGS_SCHEMA_VERSION) return { ...DEFAULT_SETTINGS };
    return normalizeSettings(parsed);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(value, storage) {
  const settings = normalizeSettings(value);
  try {
    const activeStorage = storage || window.localStorage;
    activeStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({
      schemaVersion: SETTINGS_SCHEMA_VERSION,
      ...settings,
    }));
    return true;
  } catch {
    return false;
  }
}
