export const LEVEL_CATALOG = Object.freeze([
  { id: "straight-start", file: "./levels/straight-start.json", name: "Straight Start", difficulty: "Beginning" },
  { id: "starter-l", file: "./levels/starter-l.json", name: "Starter L-Turn", difficulty: "Beginning" },
  { id: "mirror-left", file: "./levels/mirror-left.json", name: "Mirror Left", difficulty: "Beginning" },
  { id: "zigzag-run", file: "./levels/zigzag-run.json", name: "Double Turn", difficulty: "Beginning" },
  { id: "u-turn-trail", file: "./levels/u-turn-trail.json", name: "U-Turn Trail", difficulty: "Beginning" },
  { id: "switchback", file: "./levels/switchback.json", name: "Return Route", difficulty: "Beginning" },
  { id: "grand-tour", file: "./levels/grand-tour.json", name: "Four-Turn Finish", difficulty: "Beginning" },
].map((entry, index) => Object.freeze({ ...entry, sequence: index + 1 })));

export function levelEntry(levelId) {
  return LEVEL_CATALOG.find((entry) => entry.id === levelId) || null;
}

export function chooseInitialLevelId(requestedLevelId, savedLevelId) {
  return levelEntry(requestedLevelId)?.id
    || levelEntry(savedLevelId)?.id
    || LEVEL_CATALOG[0].id;
}

export function nextLevelId(currentLevelId) {
  const index = LEVEL_CATALOG.findIndex((entry) => entry.id === currentLevelId);
  return index >= 0 && index < LEVEL_CATALOG.length - 1 ? LEVEL_CATALOG[index + 1].id : null;
}
