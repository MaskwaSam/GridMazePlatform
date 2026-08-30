export const FIXED_STEP_SECONDS = 1 / 60;
export const SPEED_TO_MM_PER_SECOND = 0.625;
export const IDLE_ROTATION_DELAY_MS = 20_000;

export const DEFAULT_PHYSICS = Object.freeze({
  driveAcceleration: 900,
  brakeAcceleration: 900,
  coastDeceleration: 55,
  wallRestitution: 0.58,
  wallFriction: 0.16,
  impactMotorPauseSeconds: 0.12,
  stopVelocity: 0.75,
  maxCollisionIterations: 3,
});

const POSITION_EPSILON = 0.002;
const SWEEP_ITERATIONS = 16;
const WALL_SEGMENT_CACHE = new WeakMap();

export function normalizeHeading(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return ((number % 360) + 360) % 360;
}

export function applyHeadingOffset(currentHeading, offsetDegrees) {
  return normalizeHeading(finiteNumber(currentHeading) + finiteNumber(offsetDegrees));
}

export function clampSpeed(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(255, number));
}

export function durationSteps(seconds) {
  const number = Number(seconds);
  if (!Number.isFinite(number) || number <= 0) return 0;
  return Math.min(60 * 60 * 10, Math.ceil(number / FIXED_STEP_SECONDS));
}

export function headingVector(headingDegrees) {
  const radians = normalizeHeading(headingDegrees) * Math.PI / 180;
  return { x: Math.sin(radians), z: -Math.cos(radians) };
}

export function rollingTransformForMovement(movementX, movementZ, radius) {
  const x = Number(movementX);
  const z = Number(movementZ);
  const robotRadius = Number(radius);
  if (![x, z, robotRadius].every(Number.isFinite) || robotRadius <= 0) return null;
  const distance = Math.hypot(x, z);
  if (!distance) return null;
  return {
    axisX: z / distance,
    axisZ: -x / distance,
    angle: distance / robotRadius,
  };
}

export function shouldAutoRotateView(now, lastActivity, options = {}) {
  const currentTime = Number(now);
  const activityTime = Number(lastActivity);
  if (!Number.isFinite(currentTime) || !Number.isFinite(activityTime)) return false;
  if (
    options.moving || options.dragging || options.reducedMotion || options.hidden ||
    options.controlsDisabled || options.tourDisabled
  ) return false;
  return currentTime - activityTime >= IDLE_ROTATION_DELAY_MS;
}

export function isMazeRotationShortcut(event = {}) {
  const key = typeof event.key === "string" ? event.key.toLowerCase() : "";
  return key === "r" && event.ctrlKey === true && !event.metaKey && !event.altKey && !event.shiftKey;
}

export function mazeFogDistances(cameraDistance, footprintRadius) {
  const distance = Number(cameraDistance);
  const radius = Number(footprintRadius);
  const safeDistance = Number.isFinite(distance) && distance > 0 ? distance : 800;
  const safeRadius = Number.isFinite(radius) && radius > 0 ? radius : 300;
  const near = Math.max(1200, safeDistance + safeRadius + 100);
  const far = Math.max(2200, near + Math.max(900, safeRadius * 1.5));
  return { near, far };
}

export function physicsForLevel(level) {
  const authored = level.physics || {};
  return {
    driveAcceleration: positiveNumber(authored.driveAcceleration, DEFAULT_PHYSICS.driveAcceleration),
    brakeAcceleration: positiveNumber(authored.brakeAcceleration, DEFAULT_PHYSICS.brakeAcceleration),
    coastDeceleration: positiveNumber(authored.coastDeceleration, DEFAULT_PHYSICS.coastDeceleration),
    wallRestitution: unitNumber(authored.wallRestitution, DEFAULT_PHYSICS.wallRestitution),
    wallFriction: unitNumber(authored.wallFriction, DEFAULT_PHYSICS.wallFriction),
    impactMotorPauseSeconds: positiveNumber(authored.impactMotorPauseSeconds, DEFAULT_PHYSICS.impactMotorPauseSeconds),
    stopVelocity: positiveNumber(authored.stopVelocity, DEFAULT_PHYSICS.stopVelocity),
    maxCollisionIterations: Math.max(1, Math.min(8, Math.round(positiveNumber(
      authored.maxCollisionIterations,
      DEFAULT_PHYSICS.maxCollisionIterations,
    )))),
  };
}

export function createRobotState(level, pose = level.start) {
  return {
    x: Number(pose.x),
    z: Number(pose.z),
    heading: normalizeHeading(pose.heading ?? level.start.heading),
    speed: 0,
    actualSpeed: 0,
    velocityX: 0,
    velocityZ: 0,
    collided: false,
    collision: false,
    collisions: 0,
    collisionNormalX: 0,
    collisionNormalZ: 0,
    bounceTicks: 0,
    goalReached: false,
    distance: 0,
    movementX: 0,
    movementZ: 0,
  };
}

export function startTileForLevel(level) {
  const tile = Array.isArray(level?.tiles) ? level.tiles[0] : null;
  const tileSize = Number(level?.tileSize);
  if (!tile || !Number.isFinite(tileSize) || tileSize <= 0) return null;
  if (![tile.x, tile.z].every((value) => Number.isFinite(Number(value)))) return null;
  return tile;
}

export function isStartPlacementAllowed(level, x, z, radius = level?.robotRadius) {
  const tile = startTileForLevel(level);
  const tileSize = Number(level?.tileSize);
  const positionX = Number(x);
  const positionZ = Number(z);
  if (!tile || !Number.isFinite(positionX) || !Number.isFinite(positionZ)) return false;

  const half = tileSize / 2;
  const tileX = Number(tile.x);
  const tileZ = Number(tile.z);
  const insideStartingPiece = (
    positionX >= tileX - half - POSITION_EPSILON &&
    positionX <= tileX + half + POSITION_EPSILON &&
    positionZ >= tileZ - half - POSITION_EPSILON &&
    positionZ <= tileZ + half + POSITION_EPSILON
  );
  return insideStartingPiece && isPositionAllowed(level, positionX, positionZ, radius);
}

export function wallSegmentsForLevel(level) {
  if (WALL_SEGMENT_CACHE.has(level)) return WALL_SEGMENT_CACHE.get(level);
  const explicit = Array.isArray(level.wallSegments)
    ? level.wallSegments.map((segment, index) => normalizeWallSegment(segment, `wall-${index}`))
    : [];
  const generated = [];
  if (Array.isArray(level.tiles) && level.collisionProfiles) {
    for (const [tileIndex, tile] of level.tiles.entries()) {
      const profile = level.collisionProfiles[tile.piece];
      if (!profile) continue;
      const localSegments = Array.isArray(profile.segments)
        ? profile.segments
        : sideWallSegments(level.tileSize, profile.wallInset, profile.closedSides || []);
      for (const [segmentIndex, segment] of localSegments.entries()) {
        const start = transformTilePoint(tile, segment.x1, segment.z1);
        const end = transformTilePoint(tile, segment.x2, segment.z2);
        generated.push({
          id: `${tile.piece}-${tileIndex}-${segmentIndex}`,
          x1: start.x,
          z1: start.z,
          x2: end.x,
          z2: end.z,
        });
      }
    }
  }
  const segments = [...explicit, ...generated];
  WALL_SEGMENT_CACHE.set(level, segments);
  return segments;
}

export function isPositionAllowed(level, x, z, radius = level.robotRadius) {
  let insideNavigation = false;
  if (Array.isArray(level.navigationPolygon) && level.navigationPolygon.length >= 3) {
    if (!pointInPolygon(level.navigationPolygon, x, z)) return false;
    const minimumDistanceSquared = Math.max(0, radius - POSITION_EPSILON) ** 2;
    insideNavigation = polygonEdges(level.navigationPolygon).every((edge) => (
      pointSegmentDistanceSquared(x, z, edge.a.x, edge.a.z, edge.b.x, edge.b.z) >= minimumDistanceSquared
    ));
  } else {
    insideNavigation = (level.navigationZones || []).some((zone) => (
      x >= zone.xMin + radius && x <= zone.xMax - radius &&
      z >= zone.zMin + radius && z <= zone.zMax - radius
    ));
  }
  if (!insideNavigation) return false;
  const minimumWallDistanceSquared = Math.max(0, radius - POSITION_EPSILON) ** 2;
  return wallSegmentsForLevel(level).every((segment) => (
    pointSegmentDistanceSquared(x, z, segment.x1, segment.z1, segment.x2, segment.z2) >= minimumWallDistanceSquared
  ));
}

export function isAtGoal(level, x, z) {
  return Math.hypot(x - level.goal.x, z - level.goal.z) <= level.goal.radius;
}

export function isStoppedAtGoal(level, state) {
  if (!isAtGoal(level, Number(state.x), Number(state.z))) return false;
  if (clampSpeed(state.speed) > 0) return false;
  const physics = physicsForLevel(level);
  return Math.hypot(finiteNumber(state.velocityX), finiteNumber(state.velocityZ)) <= physics.stopVelocity;
}

export function advanceState(level, state, stepSeconds = FIXED_STEP_SECONDS) {
  if (state.goalReached) {
    return {
      ...state,
      speed: 0,
      actualSpeed: 0,
      velocityX: 0,
      velocityZ: 0,
      collision: false,
      distance: 0,
      movementX: 0,
      movementZ: 0,
    };
  }

  const physics = physicsForLevel(level);
  const commandedSpeed = clampSpeed(state.speed);
  const bounceTicks = Math.max(0, Math.round(Number(state.bounceTicks) || 0));
  let velocityX = finiteNumber(state.velocityX);
  let velocityZ = finiteNumber(state.velocityZ);

  if (commandedSpeed <= 0) {
    ({ x: velocityX, z: velocityZ } = approachVelocity(
      velocityX,
      velocityZ,
      0,
      0,
      physics.brakeAcceleration * stepSeconds,
    ));
  } else if (bounceTicks > 0) {
    ({ x: velocityX, z: velocityZ } = reduceVelocity(
      velocityX,
      velocityZ,
      physics.coastDeceleration * stepSeconds,
    ));
  } else {
    const direction = headingVector(state.heading);
    const targetVelocity = commandedSpeed * SPEED_TO_MM_PER_SECOND;
    ({ x: velocityX, z: velocityZ } = approachVelocity(
      velocityX,
      velocityZ,
      direction.x * targetVelocity,
      direction.z * targetVelocity,
      physics.driveAcceleration * stepSeconds,
    ));
  }

  const movement = moveWithCollisions(
    level,
    Number(state.x),
    Number(state.z),
    velocityX,
    velocityZ,
    stepSeconds,
    level.robotRadius,
    physics,
  );
  const distance = Math.hypot(movement.x - state.x, movement.z - state.z);
  const collision = movement.impacts > 0;
  const stopped = commandedSpeed <= 0 && (
    Math.hypot(movement.velocityX, movement.velocityZ) <= physics.stopVelocity
  );
  const goalReached = isStoppedAtGoal(level, {
    x: movement.x,
    z: movement.z,
    speed: commandedSpeed,
    velocityX: movement.velocityX,
    velocityZ: movement.velocityZ,
  });
  velocityX = stopped ? 0 : movement.velocityX;
  velocityZ = stopped ? 0 : movement.velocityZ;
  const actualSpeed = stopped
    ? 0
    : clampSpeed(Math.hypot(velocityX, velocityZ) / SPEED_TO_MM_PER_SECOND);

  return {
    ...state,
    x: movement.x,
    z: movement.z,
    heading: normalizeHeading(state.heading),
    speed: stopped ? 0 : commandedSpeed,
    actualSpeed,
    velocityX,
    velocityZ,
    collided: Boolean(state.collided) || collision,
    collision,
    collisions: Math.max(0, Math.round(Number(state.collisions) || 0)) + movement.impacts,
    collisionNormalX: collision ? movement.normalX : 0,
    collisionNormalZ: collision ? movement.normalZ : 0,
    bounceTicks: collision
      ? durationSteps(physics.impactMotorPauseSeconds)
      : Math.max(0, bounceTicks - 1),
    goalReached,
    distance,
    movementX: movement.x - state.x,
    movementZ: movement.z - state.z,
  };
}

export function simulateCommands(level, commands) {
  let state = createRobotState(level);

  for (const command of commands) {
    if (state.goalReached) break;

    if (command.command === "setHeading") {
      state = { ...state, heading: applyHeadingOffset(state.heading, command.heading) };
      continue;
    }
    if (command.command === "setSpeed") {
      state = { ...state, speed: clampSpeed(command.speed) };
      continue;
    }
    if (command.command === "stop") {
      state = settleToStop(level, { ...state, speed: 0 });
      continue;
    }
    if (command.command === "spin") {
      state = settleToStop(level, { ...state, speed: 0 });
      const startHeading = state.heading;
      const spinSteps = Math.max(1, durationSteps(command.seconds ?? 0.5));
      for (let index = 0; index < spinSteps && !state.goalReached; index += 1) {
        state = {
          ...state,
          heading: applyHeadingOffset(startHeading, Number(command.degrees || 0) * ((index + 1) / spinSteps)),
        };
        state = advanceState(level, state);
      }
      continue;
    }

    const isRoll = command.command === "roll";
    if (isRoll) {
      state = {
        ...state,
        heading: applyHeadingOffset(state.heading, command.heading),
        speed: clampSpeed(command.speed),
      };
    }
    if (isRoll || command.command === "wait") {
      const steps = durationSteps(command.seconds);
      for (let index = 0; index < steps && !state.goalReached; index += 1) {
        state = advanceState(level, state);
      }
      if (isRoll && !state.goalReached) state = settleToStop(level, { ...state, speed: 0 });
    }
  }

  return state;
}

function settleToStop(level, initialState) {
  const physics = physicsForLevel(level);
  let state = initialState;
  const maximumSteps = durationSteps(1);
  for (let index = 0; index < maximumSteps && !state.goalReached; index += 1) {
    if (Math.hypot(finiteNumber(state.velocityX), finiteNumber(state.velocityZ)) <= physics.stopVelocity) {
      const stopped = {
        ...state,
        speed: 0,
        actualSpeed: 0,
        velocityX: 0,
        velocityZ: 0,
        collision: false,
        distance: 0,
        movementX: 0,
        movementZ: 0,
      };
      return { ...stopped, goalReached: isStoppedAtGoal(level, stopped) };
    }
    state = advanceState(level, { ...state, speed: 0 });
  }
  return state;
}

function moveWithCollisions(level, x, z, velocityX, velocityZ, stepSeconds, radius, physics) {
  if (!Array.isArray(level.navigationPolygon) || level.navigationPolygon.length < 3) {
    return moveInsideLegacyZones(level, x, z, velocityX, velocityZ, stepSeconds, radius, physics);
  }

  let positionX = x;
  let positionZ = z;
  let remainingSeconds = stepSeconds;
  let impacts = 0;
  let normalX = 0;
  let normalZ = 0;

  for (let iteration = 0; iteration < physics.maxCollisionIterations && remainingSeconds > 1e-7; iteration += 1) {
    const targetX = positionX + velocityX * remainingSeconds;
    const targetZ = positionZ + velocityZ * remainingSeconds;
    if (isPositionAllowed(level, targetX, targetZ, radius)) {
      positionX = targetX;
      positionZ = targetZ;
      remainingSeconds = 0;
      break;
    }

    let allowedFraction = 0;
    let blockedFraction = 1;
    for (let sweep = 0; sweep < SWEEP_ITERATIONS; sweep += 1) {
      const fraction = (allowedFraction + blockedFraction) / 2;
      const testX = positionX + (targetX - positionX) * fraction;
      const testZ = positionZ + (targetZ - positionZ) * fraction;
      if (isPositionAllowed(level, testX, testZ, radius)) allowedFraction = fraction;
      else blockedFraction = fraction;
    }

    const hitX = positionX + (targetX - positionX) * allowedFraction;
    const hitZ = positionZ + (targetZ - positionZ) * allowedFraction;
    const boundary = nearestCollisionBoundary(level, hitX, hitZ);
    normalX = boundary.normalX;
    normalZ = boundary.normalZ;
    if (velocityX * normalX + velocityZ * normalZ > 0) {
      normalX *= -1;
      normalZ *= -1;
    }

    positionX = hitX + normalX * POSITION_EPSILON;
    positionZ = hitZ + normalZ * POSITION_EPSILON;
    const normalVelocity = velocityX * normalX + velocityZ * normalZ;
    const tangentX = velocityX - normalVelocity * normalX;
    const tangentZ = velocityZ - normalVelocity * normalZ;
    const reboundVelocity = Math.max(0, -normalVelocity) * physics.wallRestitution;
    velocityX = tangentX * (1 - physics.wallFriction) + normalX * reboundVelocity;
    velocityZ = tangentZ * (1 - physics.wallFriction) + normalZ * reboundVelocity;
    impacts += 1;
    remainingSeconds *= Math.max(0, 1 - allowedFraction);

    if (!isPositionAllowed(level, positionX, positionZ, radius)) {
      positionX = hitX;
      positionZ = hitZ;
      remainingSeconds = 0;
    }
  }

  return { x: positionX, z: positionZ, velocityX, velocityZ, impacts, normalX, normalZ };
}

function moveInsideLegacyZones(level, x, z, velocityX, velocityZ, stepSeconds, radius, physics) {
  let positionX = x;
  let positionZ = z;
  let impacts = 0;
  let normalX = 0;
  let normalZ = 0;
  const nextX = x + velocityX * stepSeconds;
  if (isPositionAllowed(level, nextX, z, radius)) positionX = nextX;
  else {
    normalX = velocityX > 0 ? -1 : 1;
    velocityX *= -physics.wallRestitution;
    velocityZ *= 1 - physics.wallFriction;
    impacts += 1;
  }
  const nextZ = z + velocityZ * stepSeconds;
  if (isPositionAllowed(level, positionX, nextZ, radius)) positionZ = nextZ;
  else {
    normalZ = velocityZ > 0 ? -1 : 1;
    velocityZ *= -physics.wallRestitution;
    velocityX *= 1 - physics.wallFriction;
    impacts += 1;
  }
  return { x: positionX, z: positionZ, velocityX, velocityZ, impacts, normalX, normalZ };
}

function nearestCollisionBoundary(level, x, z) {
  let nearest = Array.isArray(level.navigationPolygon) && level.navigationPolygon.length >= 3
    ? nearestPolygonBoundary(level.navigationPolygon, x, z)
    : null;
  for (const segment of wallSegmentsForLevel(level)) {
    const point = closestPointOnSegment(x, z, segment.x1, segment.z1, segment.x2, segment.z2);
    const deltaX = x - point.x;
    const deltaZ = z - point.z;
    const distanceSquared = deltaX * deltaX + deltaZ * deltaZ;
    if (!nearest || distanceSquared < nearest.distanceSquared) {
      const distance = Math.sqrt(distanceSquared);
      if (distance > 1e-8) {
        nearest = { distanceSquared, normalX: deltaX / distance, normalZ: deltaZ / distance };
      } else {
        const edgeX = segment.x2 - segment.x1;
        const edgeZ = segment.z2 - segment.z1;
        const edgeLength = Math.hypot(edgeX, edgeZ) || 1;
        nearest = { distanceSquared, normalX: -edgeZ / edgeLength, normalZ: edgeX / edgeLength };
      }
    }
  }
  return nearest || { distanceSquared: Infinity, normalX: 0, normalZ: 0 };
}

function nearestPolygonBoundary(polygon, x, z) {
  let nearest = null;
  for (const edge of polygonEdges(polygon)) {
    const point = closestPointOnSegment(x, z, edge.a.x, edge.a.z, edge.b.x, edge.b.z);
    const deltaX = x - point.x;
    const deltaZ = z - point.z;
    const distanceSquared = deltaX * deltaX + deltaZ * deltaZ;
    if (!nearest || distanceSquared < nearest.distanceSquared) {
      const distance = Math.sqrt(distanceSquared);
      if (distance > 1e-8) {
        nearest = { distanceSquared, normalX: deltaX / distance, normalZ: deltaZ / distance };
      } else {
        const edgeX = edge.b.x - edge.a.x;
        const edgeZ = edge.b.z - edge.a.z;
        const edgeLength = Math.hypot(edgeX, edgeZ) || 1;
        const clockwise = polygonSignedArea(polygon) < 0;
        nearest = {
          distanceSquared,
          normalX: clockwise ? edgeZ / edgeLength : -edgeZ / edgeLength,
          normalZ: clockwise ? -edgeX / edgeLength : edgeX / edgeLength,
        };
      }
    }
  }
  return nearest || { normalX: 0, normalZ: 0 };
}

function sideWallSegments(tileSize, wallInset, closedSides) {
  const half = positiveNumber(tileSize, 200) / 2;
  const inset = positiveNumber(wallInset, 19.2);
  const inner = half - inset;
  const segments = {
    north: { x1: -half, z1: -inner, x2: half, z2: -inner },
    east: { x1: inner, z1: -half, x2: inner, z2: half },
    south: { x1: half, z1: inner, x2: -half, z2: inner },
    west: { x1: -inner, z1: half, x2: -inner, z2: -half },
  };
  return closedSides.map((side) => segments[side]).filter(Boolean);
}

function transformTilePoint(tile, x, z) {
  const radians = finiteNumber(tile.yawDegrees) * Math.PI / 180;
  const cosine = Math.cos(radians);
  const sine = Math.sin(radians);
  return {
    x: finiteNumber(tile.x) + cosine * x + sine * z,
    z: finiteNumber(tile.z) - sine * x + cosine * z,
  };
}

function normalizeWallSegment(segment, fallbackId) {
  return {
    id: String(segment.id || fallbackId),
    x1: finiteNumber(segment.x1),
    z1: finiteNumber(segment.z1),
    x2: finiteNumber(segment.x2),
    z2: finiteNumber(segment.z2),
  };
}

function pointInPolygon(polygon, x, z) {
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index, index += 1) {
    const a = polygon[index];
    const b = polygon[previous];
    if (pointSegmentDistanceSquared(x, z, a.x, a.z, b.x, b.z) <= POSITION_EPSILON ** 2) return true;
    const crosses = ((a.z > z) !== (b.z > z)) &&
      (x < ((b.x - a.x) * (z - a.z)) / (b.z - a.z) + a.x);
    if (crosses) inside = !inside;
  }
  return inside;
}

function polygonEdges(polygon) {
  return polygon.map((point, index) => ({ a: point, b: polygon[(index + 1) % polygon.length] }));
}

function polygonSignedArea(polygon) {
  return polygon.reduce((area, point, index) => {
    const next = polygon[(index + 1) % polygon.length];
    return area + point.x * next.z - next.x * point.z;
  }, 0) / 2;
}

function pointSegmentDistanceSquared(x, z, x1, z1, x2, z2) {
  const point = closestPointOnSegment(x, z, x1, z1, x2, z2);
  return (x - point.x) ** 2 + (z - point.z) ** 2;
}

function closestPointOnSegment(x, z, x1, z1, x2, z2) {
  const deltaX = x2 - x1;
  const deltaZ = z2 - z1;
  const lengthSquared = deltaX * deltaX + deltaZ * deltaZ;
  if (lengthSquared <= 1e-12) return { x: x1, z: z1 };
  const fraction = Math.max(0, Math.min(1, ((x - x1) * deltaX + (z - z1) * deltaZ) / lengthSquared));
  return { x: x1 + deltaX * fraction, z: z1 + deltaZ * fraction };
}

function approachVelocity(x, z, targetX, targetZ, maximumDelta) {
  const deltaX = targetX - x;
  const deltaZ = targetZ - z;
  const distance = Math.hypot(deltaX, deltaZ);
  if (distance <= maximumDelta || distance <= 1e-9) return { x: targetX, z: targetZ };
  return { x: x + deltaX / distance * maximumDelta, z: z + deltaZ / distance * maximumDelta };
}

function reduceVelocity(x, z, amount) {
  const speed = Math.hypot(x, z);
  if (speed <= amount || speed <= 1e-9) return { x: 0, z: 0 };
  const scale = (speed - amount) / speed;
  return { x: x * scale, z: z * scale };
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function positiveNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function unitNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : fallback;
}
