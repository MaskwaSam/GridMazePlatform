#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  isPositionAllowed,
  isStartPlacementAllowed,
  simulateCommands,
  wallSegmentsForLevel,
} from "../game/js/level-logic.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const LEVELS_DIR = path.join(ROOT, "game", "levels");
const TILE_SIZE = 200;
const WALL_INSET = 19.2;
const INNER_FACE = TILE_SIZE / 2 - WALL_INSET;
const ROBOT_DIAMETER = 70;
const ROBOT_RADIUS = ROBOT_DIAMETER / 2;
const SPEED = 160;
const MILLIMETRES_PER_SECOND = SPEED * 0.625;
const START_OFFSET = 40;
const LEVEL_DIFFICULTY = "Beginning";

const PHYSICS = Object.freeze({
  driveAcceleration: 900,
  brakeAcceleration: 900,
  coastDeceleration: 55,
  wallRestitution: 0.58,
  wallFriction: 0.16,
  impactMotorPauseSeconds: 0.12,
  stopVelocity: 0.75,
  maxCollisionIterations: 3,
});

const ASSETS = Object.freeze({
  straight: "./assets/stl/maze_piece_straight_v1.stl",
  corner: "./assets/stl/maze_piece_corner_v1.stl",
  end: "./assets/stl/maze_piece_end_v1.stl",
});

const COLLISION_PROFILES = Object.freeze({
  straight: { closedSides: ["north", "south"], wallInset: WALL_INSET },
  corner: { closedSides: ["south", "west"], wallInset: WALL_INSET },
  end: { closedSides: ["east", "south", "west"], wallInset: WALL_INSET },
});

const SIDE_VECTORS = Object.freeze({
  north: { x: 0, z: -1, heading: 0 },
  east: { x: 1, z: 0, heading: 90 },
  south: { x: 0, z: 1, heading: 180 },
  west: { x: -1, z: 0, heading: 270 },
});

const LEVEL_DEFINITIONS = Object.freeze([
  {
    id: "straight-start",
    name: "Straight Start",
    description: "Learn speed and timing by stopping on the goal.",
    difficulty: LEVEL_DIFFICULTY,
    concepts: ["forward", "speed", "time"],
    path: [[0, 1], [0, 0], [0, -1]],
  },
  {
    id: "starter-l",
    name: "Starter L-Turn",
    description: "Drive north, turn right, and stop on the glowing goal.",
    difficulty: LEVEL_DIFFICULTY,
    concepts: ["forward", "right turn"],
    path: [[0, 1], [0, 0], [0, -1], [1, -1]],
  },
  {
    id: "mirror-left",
    name: "Mirror Left",
    description: "Mirror the starter route by making a left turn at the corner.",
    difficulty: LEVEL_DIFFICULTY,
    concepts: ["forward", "left turn", "negative angles"],
    path: [[0, 1], [0, 0], [0, -1], [-1, -1]],
  },
  {
    id: "zigzag-run",
    name: "Double Turn",
    description: "Combine a right turn and a left turn without touching the walls.",
    difficulty: LEVEL_DIFFICULTY,
    concepts: ["right turn", "left turn", "sequence"],
    path: [[-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1], [1, -2]],
  },
  {
    id: "u-turn-trail",
    name: "U-Turn Trail",
    description: "Use two right turns to travel around the long U-shaped route.",
    difficulty: LEVEL_DIFFICULTY,
    concepts: ["repeated turns", "southbound travel"],
    path: [[-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1], [1, 0], [1, 1]],
  },
  {
    id: "switchback",
    name: "Return Route",
    description: "Navigate three turns and reverse across the maze before finishing.",
    difficulty: LEVEL_DIFFICULTY,
    concepts: ["mixed turns", "westbound travel", "debugging"],
    path: [[-1, 2], [-1, 1], [-1, 0], [0, 0], [1, 0], [1, -1], [1, -2], [0, -2], [-1, -2]],
  },
  {
    id: "grand-tour",
    name: "Four-Turn Finish",
    description: "Solve the final mixed-turn route using four changes of direction.",
    difficulty: LEVEL_DIFFICULTY,
    concepts: ["mixed turns", "planning", "multi-step program"],
    path: [[-1, 2], [-1, 1], [-1, 0], [0, 0], [1, 0], [1, 1], [2, 1], [2, 0], [2, -1]],
  },
]);

const mode = process.argv.includes("--write") ? "write" : "check";
const generated = LEVEL_DEFINITIONS.map((definition, index) => buildLevel(definition, index + 1));
let mismatches = 0;

for (const level of generated) {
  validateLevel(level);
  const filename = `${level.id}.json`;
  const destination = path.join(LEVELS_DIR, filename);
  const content = `${JSON.stringify(level, null, 2)}\n`;
  if (mode === "write") {
    fs.mkdirSync(LEVELS_DIR, { recursive: true });
    fs.writeFileSync(destination, content);
    console.log(`WROTE game/levels/${filename}`);
  } else if (!fs.existsSync(destination) || fs.readFileSync(destination, "utf8") !== content) {
    mismatches += 1;
    console.error(`OUT OF DATE game/levels/${filename}`);
  } else {
    console.log(`OK game/levels/${filename}`);
  }
}

if (mode === "check" && mismatches) {
  console.error(`\n${mismatches} generated level file(s) need: node scripts/generate_game_levels.mjs --write`);
  process.exitCode = 1;
} else {
  console.log(`\n${generated.length} level definitions validated.`);
}

function buildLevel(definition, sequence) {
  validatePath(definition);
  const centres = definition.path.map(([gridX, gridZ]) => ({
    x: gridX * TILE_SIZE,
    z: gridZ * TILE_SIZE,
  }));
  const tiles = centres.map((centre, index) => tileForPath(centres, index));
  const firstDirection = directionBetween(centres[0], centres[1]);
  const start = {
    x: centres[0].x - firstDirection.x * START_OFFSET,
    z: centres[0].z - firstDirection.z * START_OFFSET,
    heading: firstDirection.heading,
  };
  const goalCentre = centres.at(-1);
  const navigationPolygon = unionPolygon(tiles.map(navigationRectangle));

  return {
    schemaVersion: 2,
    id: definition.id,
    sequence,
    name: definition.name,
    description: definition.description,
    difficulty: definition.difficulty,
    concepts: definition.concepts,
    units: "millimetres",
    tileSize: TILE_SIZE,
    baseTop: 10,
    robotDiameter: ROBOT_DIAMETER,
    robotRadius: ROBOT_RADIUS,
    physics: PHYSICS,
    start,
    goal: { x: goalCentre.x, z: goalCentre.z, radius: 38 },
    tray: { x: centres[0].x - 180, z: centres[0].z + 35 },
    assets: ASSETS,
    collisionProfiles: COLLISION_PROFILES,
    tiles,
    navigationPolygon,
    referenceSolution: referenceSolution(centres, firstDirection.heading),
  };
}

function validatePath(definition) {
  if (!definition.id || !/^[a-z0-9-]+$/.test(definition.id)) throw new Error(`Invalid level id: ${definition.id}`);
  if (!Array.isArray(definition.path) || definition.path.length < 3) throw new Error(`${definition.id}: path needs at least three tiles`);
  const seen = new Set();
  definition.path.forEach(([x, z], index) => {
    const key = `${x},${z}`;
    if (seen.has(key)) throw new Error(`${definition.id}: tile ${key} is repeated`);
    seen.add(key);
    if (!index) return;
    const [previousX, previousZ] = definition.path[index - 1];
    if (Math.abs(x - previousX) + Math.abs(z - previousZ) !== 1) {
      throw new Error(`${definition.id}: ${previousX},${previousZ} to ${x},${z} is not adjacent`);
    }
  });
  const [firstX, firstZ] = definition.path[0];
  const [secondX, secondZ] = definition.path[1];
  if (secondX !== firstX || secondZ !== firstZ - 1) {
    throw new Error(`${definition.id}: classroom levels must start facing north`);
  }
}

function tileForPath(centres, index) {
  const centre = centres[index];
  const openings = [];
  if (index > 0) openings.push(directionBetween(centre, centres[index - 1]).side);
  if (index < centres.length - 1) openings.push(directionBetween(centre, centres[index + 1]).side);
  const sorted = openings.slice().sort().join("+");
  const mapping = {
    north: ["end", 0],
    west: ["end", 90],
    south: ["end", 180],
    east: ["end", -90],
    "east+west": ["straight", 0],
    "north+south": ["straight", 90],
    "east+north": ["corner", 0],
    "north+west": ["corner", 90],
    "south+west": ["corner", 180],
    "east+south": ["corner", -90],
  };
  const [piece, yawDegrees] = mapping[sorted] || [];
  if (!piece) throw new Error(`Unsupported openings at ${centre.x},${centre.z}: ${sorted}`);
  return { piece, x: centre.x, z: centre.z, yawDegrees };
}

function directionBetween(from, to) {
  const x = Math.sign(to.x - from.x);
  const z = Math.sign(to.z - from.z);
  const entry = Object.entries(SIDE_VECTORS).find(([, vector]) => vector.x === x && vector.z === z);
  if (!entry) throw new Error(`Non-cardinal path from ${from.x},${from.z} to ${to.x},${to.z}`);
  return { side: entry[0], ...entry[1] };
}

function transformedOpenings(tile) {
  const localOpenings = tile.piece === "straight" ? ["east", "west"]
    : tile.piece === "corner" ? ["north", "east"]
      : ["north"];
  const radians = tile.yawDegrees * Math.PI / 180;
  const cosine = Math.cos(radians);
  const sine = Math.sin(radians);
  return localOpenings.map((side) => {
    const vector = SIDE_VECTORS[side];
    const worldX = Math.round(cosine * vector.x + sine * vector.z);
    const worldZ = Math.round(-sine * vector.x + cosine * vector.z);
    return Object.entries(SIDE_VECTORS).find(([, candidate]) => candidate.x === worldX && candidate.z === worldZ)[0];
  });
}

function navigationRectangle(tile) {
  const openings = new Set(transformedOpenings(tile));
  return {
    xMin: tile.x - (openings.has("west") ? TILE_SIZE / 2 : INNER_FACE),
    xMax: tile.x + (openings.has("east") ? TILE_SIZE / 2 : INNER_FACE),
    zMin: tile.z - (openings.has("north") ? TILE_SIZE / 2 : INNER_FACE),
    zMax: tile.z + (openings.has("south") ? TILE_SIZE / 2 : INNER_FACE),
  };
}

function unionPolygon(rectangles) {
  const xs = uniqueSorted(rectangles.flatMap((rectangle) => [rectangle.xMin, rectangle.xMax]));
  const zs = uniqueSorted(rectangles.flatMap((rectangle) => [rectangle.zMin, rectangle.zMax]));
  const occupied = Array.from({ length: xs.length - 1 }, () => Array(zs.length - 1).fill(false));
  for (let xIndex = 0; xIndex < xs.length - 1; xIndex += 1) {
    for (let zIndex = 0; zIndex < zs.length - 1; zIndex += 1) {
      const x = (xs[xIndex] + xs[xIndex + 1]) / 2;
      const z = (zs[zIndex] + zs[zIndex + 1]) / 2;
      occupied[xIndex][zIndex] = rectangles.some((rectangle) => (
        x > rectangle.xMin && x < rectangle.xMax && z > rectangle.zMin && z < rectangle.zMax
      ));
    }
  }

  const edges = [];
  const add = (x1, z1, x2, z2) => edges.push({ x1, z1, x2, z2, used: false });
  for (let xIndex = 0; xIndex < occupied.length; xIndex += 1) {
    for (let zIndex = 0; zIndex < occupied[xIndex].length; zIndex += 1) {
      if (!occupied[xIndex][zIndex]) continue;
      const x0 = xs[xIndex];
      const x1 = xs[xIndex + 1];
      const z0 = zs[zIndex];
      const z1 = zs[zIndex + 1];
      if (!occupied[xIndex]?.[zIndex - 1]) add(x0, z0, x1, z0);
      if (!occupied[xIndex + 1]?.[zIndex]) add(x1, z0, x1, z1);
      if (!occupied[xIndex]?.[zIndex + 1]) add(x1, z1, x0, z1);
      if (!occupied[xIndex - 1]?.[zIndex]) add(x0, z1, x0, z0);
    }
  }

  const outgoing = new Map();
  for (const edge of edges) {
    const key = pointKey(edge.x1, edge.z1);
    if (!outgoing.has(key)) outgoing.set(key, []);
    outgoing.get(key).push(edge);
  }
  const loops = [];
  for (const first of edges) {
    if (first.used) continue;
    const points = [{ x: first.x1, z: first.z1 }];
    let edge = first;
    while (true) {
      edge.used = true;
      const nextPoint = { x: edge.x2, z: edge.z2 };
      if (pointKey(nextPoint.x, nextPoint.z) === pointKey(points[0].x, points[0].z)) break;
      points.push(nextPoint);
      const choices = (outgoing.get(pointKey(nextPoint.x, nextPoint.z)) || []).filter((candidate) => !candidate.used);
      if (choices.length !== 1) throw new Error(`Traversable outline branches at ${nextPoint.x},${nextPoint.z}`);
      [edge] = choices;
    }
    loops.push(simplifyPolygon(points));
  }
  if (loops.length !== 1) throw new Error(`Level outline contains ${loops.length} boundaries; paths with holes are unsupported`);
  return loops[0];
}

function simplifyPolygon(points) {
  let simplified = points;
  let changed = true;
  while (changed && simplified.length > 3) {
    changed = false;
    simplified = simplified.filter((point, index, source) => {
      const previous = source[(index - 1 + source.length) % source.length];
      const next = source[(index + 1) % source.length];
      const collinear = (previous.x === point.x && point.x === next.x) || (previous.z === point.z && point.z === next.z);
      if (collinear) changed = true;
      return !collinear;
    });
  }
  return simplified;
}

function referenceSolution(centres, initialHeading) {
  const runs = [];
  for (let index = 1; index < centres.length; index += 1) {
    const heading = directionBetween(centres[index - 1], centres[index]).heading;
    if (runs.at(-1)?.heading === heading) runs.at(-1).edges += 1;
    else runs.push({ heading, edges: 1 });
  }
  const commands = [];
  let heading = initialHeading;
  runs.forEach((run, index) => {
    if (run.heading !== heading) {
      let degrees = ((run.heading - heading + 540) % 360) - 180;
      if (degrees === -180) degrees = 180;
      commands.push({ command: "spin", degrees, seconds: 0.5 });
      heading = run.heading;
    }
    const distance = run.edges * TILE_SIZE + (index === 0 ? START_OFFSET : 0);
    commands.push({ command: "roll", heading: 0, speed: SPEED, seconds: distance / MILLIMETRES_PER_SECOND });
  });
  return commands;
}

function validateLevel(level) {
  if (!isStartPlacementAllowed(level, level.start.x, level.start.z)) {
    throw new Error(`${level.id}: start is not legal on the first printable piece`);
  }
  if (!isPositionAllowed(level, level.goal.x, level.goal.z)) throw new Error(`${level.id}: goal is illegal`);
  if (!wallSegmentsForLevel(level).length) throw new Error(`${level.id}: no wall segments`);
  const state = simulateCommands(level, level.referenceSolution);
  if (
    !state.goalReached || state.actualSpeed !== 0 || state.velocityX !== 0 || state.velocityZ !== 0 ||
    state.collisions !== 0 || !isPositionAllowed(level, state.x, state.z)
  ) {
    throw new Error(`${level.id}: reference route failed at x=${state.x}, z=${state.z}, collisions=${state.collisions}`);
  }
  const nominalSeconds = level.referenceSolution.reduce((total, command) => total + Number(command.seconds || 0), 0);
  if (nominalSeconds >= 23) throw new Error(`${level.id}: ${nominalSeconds}s reference route is too close to the 25s browser limit`);
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((first, second) => first - second);
}

function pointKey(x, z) {
  return `${x},${z}`;
}
