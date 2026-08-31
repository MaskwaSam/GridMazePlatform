import * as THREE from "three";
import { OrbitControls } from "../vendor/three/OrbitControls.js";
import { STLLoader } from "../vendor/three/STLLoader.js";
import {
  FIXED_STEP_SECONDS,
  IDLE_ROTATION_DELAY_MS,
  applyHeadingOffset,
  advanceState,
  clampSpeed,
  createRobotState,
  durationSteps,
  isPositionAllowed,
  isStartPlacementAllowed,
  isStoppedAtGoal,
  mazeFogDistances,
  physicsForLevel,
  rollingTransformForMovement,
  shouldAutoRotateView,
  startTileForLevel,
  validatePlayableLevel,
} from "./level-logic.js?v=36";

const MAX_TICKS_PER_FRAME = 8;
const ROBOT_MODEL_RADIUS = 18;
const ROLL_INDICATOR_ARC = Math.PI * 0.32;
const IDLE_ROTATION_SPEED = 0.5;
const DEFAULT_FOG = Object.freeze({ near: 850, far: 1450 });
const DEFAULT_VISUAL_SETTINGS = Object.freeze({
  idleTour: true,
  reduceMotion: false,
  clearView: false,
  showTrail: true,
  showImpactMarkers: true,
  showGrid: true,
});

export class MazeSimulation {
  constructor(canvas, callbacks = {}) {
    this.canvas = canvas;
    this.callbacks = callbacks;
    this.level = null;
    this.placed = false;
    this.startPose = null;
    this.dragging = false;
    this.dragPointerId = null;
    this.motion = null;
    this.fixedAccumulator = 0;
    this.lastFrameTime = performance.now();
    this.lastViewActivityTime = this.lastFrameTime;
    this.idleTourEnabled = true;
    this.visualSettings = { ...DEFAULT_VISUAL_SETTINGS };
    this.fogDistances = { ...DEFAULT_FOG };
    this.hasImpactMarker = false;
    this.collisions = 0;
    this.trailPoints = [];
    this.matrix = new Array(64).fill("#000000");
    this.state = {
      x: 0, z: 0, heading: 0, speed: 0, actualSpeed: 0,
      velocityX: 0, velocityZ: 0, collided: false, collision: false,
      collisions: 0, goalReached: false, distance: 0, movementX: 0, movementZ: 0,
    };
    this.setupScene();
    this.setupInteraction();
    this.animate = this.animate.bind(this);
    requestAnimationFrame(this.animate);
  }

  setupScene() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xdcebf1);
    this.scene.fog = new THREE.Fog(0xdcebf1, this.fogDistances.near, this.fogDistances.far);

    this.camera = new THREE.PerspectiveCamera(42, 1, 1, 2600);
    this.camera.position.set(520, 480, 540);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.enablePan = false;
    this.controls.autoRotate = false;
    this.controls.autoRotateSpeed = IDLE_ROTATION_SPEED;
    this.controls.minDistance = 380;
    this.controls.maxDistance = 1100;
    this.controls.minPolarAngle = Math.PI * 0.18;
    this.controls.maxPolarAngle = Math.PI * 0.46;
    this.controls.target.set(55, 0, -75);
    this.controls.update();

    this.scene.add(new THREE.HemisphereLight(0xf1fbff, 0x526b73, 2.25));
    const sun = new THREE.DirectionalLight(0xffffff, 2.4);
    sun.position.set(-280, 600, 340);
    this.scene.add(sun);

    this.ground = new THREE.Mesh(
      new THREE.CircleGeometry(780, 80),
      new THREE.MeshStandardMaterial({ color: 0xc8dce4, roughness: 0.96, metalness: 0 }),
    );
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.position.set(60, -2.5, -70);
    this.scene.add(this.ground);

    this.grid = new THREE.GridHelper(1000, 20, 0x79a2b2, 0xa9c5d0);
    this.grid.position.y = -1.8;
    this.scene.add(this.grid);

    this.mazeGroup = new THREE.Group();
    this.scene.add(this.mazeGroup);
    this.addTray();
    this.addRobot();
    this.addTrail();
    this.addCollisionMarker();

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.canvas.parentElement);
    this.resize();
  }

  async loadLevel(level) {
    validatePlayableLevel(level);
    this.cancelDrag();
    const loader = new STLLoader();
    const usedPieces = [...new Set(level.tiles.map((tile) => tile.piece))];
    const loads = await Promise.allSettled(usedPieces.map(async (piece) => {
      const assetPath = level.assets[piece];
      if (!assetPath) throw new Error(`Level ${level.id} is missing the ${piece} STL asset.`);
      const geometry = await loader.loadAsync(assetPath);
      geometry.rotateX(-Math.PI / 2);
      geometry.translate(-level.tileSize / 2, 0, level.tileSize / 2);
      geometry.computeVertexNormals();
      return [piece, geometry];
    }));
    const failedLoad = loads.find((result) => result.status === "rejected");
    if (failedLoad) {
      for (const result of loads) if (result.status === "fulfilled") result.value[1].dispose();
      throw failedLoad.reason;
    }

    const geometries = new Map(loads.map((result) => result.value));
    const colours = { straight: 0x8fb5be, corner: 0x7caab4, end: 0x689ba8 };
    const materials = new Map(usedPieces.map((piece) => [
      piece,
      new THREE.MeshStandardMaterial({ color: colours[piece] || colours.straight, roughness: 0.52, metalness: 0.05 }),
    ]));
    const nextMazeGroup = new THREE.Group();
    let markers;
    try {
      for (const tile of level.tiles) {
        const mesh = new THREE.Mesh(geometries.get(tile.piece), materials.get(tile.piece));
        mesh.position.set(tile.x, 0, tile.z);
        mesh.rotation.y = THREE.MathUtils.degToRad(tile.yawDegrees);
        mesh.userData.tile = tile;
        nextMazeGroup.add(mesh);
      }
      markers = this.createZoneMarkers(level, nextMazeGroup);
    } catch (error) {
      disposeObject3D(nextMazeGroup);
      throw error;
    }

    this.fogDistances = { ...DEFAULT_FOG };
    let view = null;
    if (Array.isArray(level.navigationPolygon) && level.navigationPolygon.length) {
      const xs = level.navigationPolygon.map((point) => point.x);
      const zs = level.navigationPolygon.map((point) => point.z);
      const xMin = Math.min(...xs, level.tray.x - 62);
      const xMax = Math.max(...xs, level.tray.x + 62);
      const zMin = Math.min(...zs, level.tray.z - 62);
      const zMax = Math.max(...zs, level.tray.z + 62);
      const spanX = xMax - xMin;
      const spanZ = zMax - zMin;
      const span = Math.max(spanX, spanZ);
      const footprintRadius = Math.hypot(spanX, spanZ) / 2;
      const cameraDistance = Math.max(800, Math.min(1800, Math.hypot(spanX, spanZ) * 1.25));
      const maxCameraDistance = Math.max(1100, cameraDistance * 1.25);
      const viewDirection = new THREE.Vector3(0.72, 0.9, 0.72).normalize().multiplyScalar(cameraDistance);
      view = {
        centreX: (xMin + xMax) / 2,
        centreZ: (zMin + zMax) / 2,
        span,
        footprintRadius,
        cameraDistance,
        maxCameraDistance,
        viewDirection,
      };
    }

    const previousMazeGroup = this.mazeGroup;
    this.scene.remove(previousMazeGroup);
    disposeObject3D(previousMazeGroup);
    this.mazeGroup = nextMazeGroup;
    this.scene.add(this.mazeGroup);
    this.level = level;
    this.robotY = level.baseTop + level.robotRadius;
    this.robot.scale.setScalar(level.robotRadius / ROBOT_MODEL_RADIUS);
    this.collisionMarker.scale.setScalar(level.robotRadius / ROBOT_MODEL_RADIUS);
    Object.assign(this, markers);

    if (view) {
      this.controls.target.set(view.centreX, 0, view.centreZ);
      this.camera.position.set(
        view.centreX + view.viewDirection.x,
        view.viewDirection.y,
        view.centreZ + view.viewDirection.z,
      );
      this.controls.maxDistance = view.maxCameraDistance;
      const fog = mazeFogDistances(view.maxCameraDistance, view.footprintRadius);
      this.fogDistances = { near: fog.near, far: fog.far };
      this.camera.far = Math.max(2600, fog.far + 500);
      this.camera.updateProjectionMatrix();
      this.ground.position.x = view.centreX;
      this.ground.position.z = view.centreZ;
      this.grid.position.x = view.centreX;
      this.grid.position.z = view.centreZ;
      const groundScale = Math.max(1, (view.span + 500) / 1560);
      this.ground.scale.set(groundScale, groundScale, groundScale);
      const gridScale = Math.max(1, (view.span + 200) / 1000);
      this.grid.scale.set(gridScale, gridScale, gridScale);
      this.controls.update();
    }
    this.noteViewActivity();
    this.tray.position.set(level.tray.x, 3, level.tray.z);
    this.trayLabel.position.set(level.tray.x, 18, level.tray.z + 68);
    this.reset(false);
    this.applyVisualSettings(this.visualSettings);
    this.emitCallback("onLoaded");
  }

  addTray() {
    this.tray = new THREE.Group();
    const plate = new THREE.Mesh(
      new THREE.CylinderGeometry(57, 61, 6, 48),
      new THREE.MeshStandardMaterial({ color: 0x203f53, roughness: 0.62, metalness: 0.22 }),
    );
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(50, 2.3, 10, 64),
      new THREE.MeshBasicMaterial({ color: 0x7ad7e2 }),
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 4;
    this.tray.add(plate, ring);
    this.scene.add(this.tray);
    this.trayLabel = createLabel("ROBOT TRAY", "#102a43", "#c9f3f6");
    this.scene.add(this.trayLabel);
  }

  addRobot() {
    this.robot = new THREE.Group();
    this.robot.userData.robot = true;
    this.robotMaterial = new THREE.MeshPhysicalMaterial({
      color: 0x59bfff,
      emissive: 0x082f4d,
      emissiveIntensity: 0.34,
      roughness: 0.23,
      metalness: 0.08,
      clearcoat: 1,
      clearcoatRoughness: 0.16,
    });
    this.robotSphere = new THREE.Mesh(
      new THREE.SphereGeometry(ROBOT_MODEL_RADIUS, 36, 24),
      this.robotMaterial,
    );
    this.robotSphere.userData.robot = true;
    const equator = new THREE.Mesh(
      new THREE.TorusGeometry(18.15, 0.65, 8, 64),
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.88 }),
    );
    equator.userData.robot = true;
    this.rollIndicator = new THREE.Mesh(
      new THREE.TorusGeometry(18.15, 1.05, 8, 16, ROLL_INDICATOR_ARC),
      new THREE.MeshBasicMaterial({ color: 0xff8a1f, toneMapped: false }),
    );
    this.rollIndicator.rotation.z = Math.PI / 2 - ROLL_INDICATOR_ARC / 2;
    this.rollIndicator.userData.robot = true;
    this.headingMarker = new THREE.Group();
    const arrow = new THREE.Mesh(
      new THREE.ConeGeometry(4.2, 14, 14),
      new THREE.MeshBasicMaterial({ color: 0xffffff }),
    );
    arrow.rotation.x = -Math.PI / 2;
    arrow.position.set(0, 19, -9);
    arrow.userData.robot = true;
    this.headingMarker.add(arrow);
    this.robotSphere.add(equator, this.rollIndicator);
    this.robot.add(this.robotSphere, this.headingMarker);
    this.scene.add(this.robot);
  }

  addTrail() {
    this.trailGeometry = new THREE.BufferGeometry();
    this.trail = new THREE.Line(
      this.trailGeometry,
      new THREE.LineBasicMaterial({ color: 0xf17935, transparent: true, opacity: 0.92 }),
    );
    this.scene.add(this.trail);
  }

  addCollisionMarker() {
    this.collisionMarker = new THREE.Mesh(
      new THREE.TorusGeometry(13, 2.5, 10, 40),
      new THREE.MeshBasicMaterial({ color: 0xe34535 }),
    );
    this.collisionMarker.rotation.x = -Math.PI / 2;
    this.collisionMarker.visible = false;
    this.scene.add(this.collisionMarker);
  }

  createZoneMarkers(level, group) {
    const makeDisc = (radius, colour) => {
      const mesh = new THREE.Mesh(
        new THREE.CylinderGeometry(radius, radius, 2.1, 64),
        new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 0.62, transparent: true, opacity: 0.72 }),
      );
      mesh.position.y = level.baseTop + 1.2;
      return mesh;
    };
    const startTile = startTileForLevel(level);
    const startMarker = new THREE.Mesh(
      new THREE.PlaneGeometry(level.tileSize - 4, level.tileSize - 4),
      new THREE.MeshStandardMaterial({
        color: 0x198fd1,
        emissive: 0x198fd1,
        emissiveIntensity: 0.48,
        transparent: true,
        opacity: 0.34,
        depthWrite: false,
      }),
    );
    startMarker.rotation.x = -Math.PI / 2;
    startMarker.position.set(startTile.x, level.baseTop + 1.1, startTile.z);
    const goalMarker = makeDisc(level.goal.radius, 0x28ad70);
    goalMarker.position.x = level.goal.x;
    goalMarker.position.z = level.goal.z;
    group.add(startMarker, goalMarker);

    const startLabel = createLabel("START AREA · NORTH", "#ffffff", "#1479cc");
    startLabel.position.set(startTile.x, 92, startTile.z);
    const goalLabel = createLabel("STOP ON GOAL", "#ffffff", "#16845b");
    goalLabel.position.set(level.goal.x, 92, level.goal.z);
    group.add(startLabel, goalLabel);
    return { startMarker, goalMarker, startLabel, goalLabel };
  }

  setupInteraction() {
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

    this.canvas.addEventListener("pointerdown", (event) => {
      this.canvas.focus({ preventScroll: true });
      if (!this.level || this.motion) return;
      this.updatePointer(event);
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const hitRobot = this.raycaster.intersectObject(this.robot, true).some((hit) => hit.object.userData.robot);
      if (!hitRobot) return;
      event.preventDefault();
      this.dragging = true;
      this.dragPointerId = event.pointerId;
      this.controls.enabled = false;
      this.canvas.classList.add("is-dragging");
      this.canvas.setPointerCapture(event.pointerId);
    });

    this.canvas.addEventListener("pointermove", (event) => {
      if (!this.dragging) return;
      this.updatePointer(event);
      this.raycaster.setFromCamera(this.pointer, this.camera);
      this.dragPlane.constant = -this.robotY;
      const point = new THREE.Vector3();
      if (this.raycaster.ray.intersectPlane(this.dragPlane, point)) {
        this.robot.position.set(point.x, this.robotY, point.z);
      }
    });

    const finishDrag = (event) => {
      if (!this.endDrag(event)) return;
      const dropPose = { x: this.robot.position.x, z: this.robot.position.z };
      if (isStartPlacementAllowed(this.level, dropPose.x, dropPose.z)) this.placeOnStart(dropPose);
      else this.returnToTray();
    };
    this.canvas.addEventListener("pointerup", finishDrag);
    this.canvas.addEventListener("pointercancel", finishDrag);

    this.reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    this.handleViewActivity = () => this.noteViewActivity();
    this.handleActivePointerMove = (event) => {
      if (event.buttons || event.pressure > 0) this.noteViewActivity();
    };
    for (const eventName of ["pointerdown", "pointerup", "wheel", "keydown"]) {
      window.addEventListener(eventName, this.handleViewActivity, { capture: true, passive: true });
    }
    window.addEventListener("pointermove", this.handleActivePointerMove, { capture: true, passive: true });
    document.addEventListener("visibilitychange", this.handleViewActivity, { passive: true });
    this.handleReducedMotionChange = () => {
      this.noteViewActivity();
      this.applyVisualSettings(this.visualSettings);
    };
    this.reducedMotionQuery.addEventListener?.("change", this.handleReducedMotionChange);
    this.canvas.dataset.idleRotating = "false";
  }

  emitCallback(name, ...args) {
    try {
      this.callbacks[name]?.(...args);
    } catch (error) {
      console.error(`Maze simulation ${name} callback failed.`, error);
    }
  }

  noteViewActivity(time = performance.now()) {
    this.lastViewActivityTime = time;
    this.controls.autoRotate = false;
    this.canvas.dataset.idleRotating = "false";
  }

  setIdleTourEnabled(enabled) {
    this.idleTourEnabled = Boolean(enabled);
    this.visualSettings.idleTour = this.idleTourEnabled;
    this.canvas.dataset.idleTourEnabled = String(this.idleTourEnabled);
    this.noteViewActivity();
    return this.idleTourEnabled;
  }

  startIdleTour(time = performance.now()) {
    this.idleTourEnabled = true;
    this.visualSettings.idleTour = true;
    this.canvas.dataset.idleTourEnabled = "true";
    this.lastViewActivityTime = time - IDLE_ROTATION_DELAY_MS;
    this.updateIdleRotation(time);
    return this.controls.autoRotate;
  }

  updateIdleRotation(time) {
    if (this.motion || this.dragging) this.lastViewActivityTime = time;
    const autoRotate = shouldAutoRotateView(time, this.lastViewActivityTime, {
      moving: Boolean(this.motion),
      dragging: this.dragging,
      reducedMotion: this.isReducedMotionActive(),
      hidden: document.hidden,
      controlsDisabled: !this.controls.enabled,
      tourDisabled: !this.idleTourEnabled,
    });
    if (autoRotate === this.controls.autoRotate) return;
    this.controls.autoRotate = autoRotate;
    this.canvas.dataset.idleRotating = String(autoRotate);
  }

  isReducedMotionActive() {
    return Boolean(this.visualSettings.reduceMotion || this.reducedMotionQuery?.matches);
  }

  applyVisualSettings(settings = {}) {
    this.visualSettings = {
      ...DEFAULT_VISUAL_SETTINGS,
      ...settings,
      idleTour: Boolean(settings.idleTour ?? DEFAULT_VISUAL_SETTINGS.idleTour),
      reduceMotion: Boolean(settings.reduceMotion ?? DEFAULT_VISUAL_SETTINGS.reduceMotion),
      clearView: Boolean(settings.clearView ?? DEFAULT_VISUAL_SETTINGS.clearView),
      showTrail: Boolean(settings.showTrail ?? DEFAULT_VISUAL_SETTINGS.showTrail),
      showImpactMarkers: Boolean(settings.showImpactMarkers ?? DEFAULT_VISUAL_SETTINGS.showImpactMarkers),
      showGrid: Boolean(settings.showGrid ?? DEFAULT_VISUAL_SETTINGS.showGrid),
    };
    this.idleTourEnabled = this.visualSettings.idleTour;
    this.applyFogPreference();
    if (this.trail) this.trail.visible = this.visualSettings.showTrail;
    if (this.grid) this.grid.visible = this.visualSettings.showGrid;
    if (this.collisionMarker) {
      this.collisionMarker.visible = this.visualSettings.showImpactMarkers && this.hasImpactMarker;
    }
    if (!this.idleTourEnabled || this.isReducedMotionActive()) this.noteViewActivity();
    this.canvas.dataset.idleTourEnabled = String(this.idleTourEnabled);
    this.canvas.dataset.reduceMotion = String(this.visualSettings.reduceMotion);
    this.canvas.dataset.reducedMotionActive = String(this.isReducedMotionActive());
    this.canvas.dataset.clearView = String(this.visualSettings.clearView);
    this.canvas.dataset.showTrail = String(this.visualSettings.showTrail);
    this.canvas.dataset.showImpactMarkers = String(this.visualSettings.showImpactMarkers);
    this.canvas.dataset.showGrid = String(this.visualSettings.showGrid);
    return { ...this.visualSettings };
  }

  applyFogPreference() {
    if (!this.scene) return;
    if (this.visualSettings.clearView) {
      this.scene.fog = null;
      return;
    }
    if (!this.scene.fog) {
      this.scene.fog = new THREE.Fog(0xdcebf1, this.fogDistances.near, this.fogDistances.far);
      return;
    }
    this.scene.fog.near = this.fogDistances.near;
    this.scene.fog.far = this.fogDistances.far;
  }

  endDrag(event = null) {
    if (!this.dragging) return false;
    this.dragging = false;
    this.controls.enabled = true;
    this.canvas.classList.remove("is-dragging");
    const pointerId = event?.pointerId ?? this.dragPointerId;
    if (pointerId !== null) {
      try { this.canvas.releasePointerCapture(pointerId); } catch { /* capture may already be released */ }
    }
    this.dragPointerId = null;
    return true;
  }

  cancelDrag() {
    if (!this.endDrag()) return;
    this.updateRobotTransform();
  }

  updatePointer(event) {
    const bounds = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    this.pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  }

  placeOnStart(pose = this.level?.start) {
    if (!this.level || this.motion) return;
    const requestedPose = {
      x: Number(pose?.x),
      z: Number(pose?.z),
    };
    const position = isStartPlacementAllowed(this.level, requestedPose.x, requestedPose.z)
      ? requestedPose
      : { x: this.level.start.x, z: this.level.start.z };
    this.startPose = {
      x: position.x,
      z: position.z,
      heading: this.level.start.heading,
    };
    this.placed = true;
    this.state = createRobotState(this.level, this.startPose);
    this.collisions = 0;
    this.hasImpactMarker = false;
    this.collisionMarker.visible = false;
    this.goalMarker && (this.goalMarker.material.emissiveIntensity = 0.62);
    this.clearTrail();
    this.robotSphere.quaternion.identity();
    this.updateRobotTransform();
    this.emitCallback("onPlacement", true, { ...this.startPose });
    this.emitTelemetry();
  }

  captureSession() {
    return {
      placed: this.placed,
      startPose: this.startPose ? { ...this.startPose } : null,
      state: { ...this.state },
      collisions: this.collisions,
      matrix: [...this.matrix],
      robotQuaternion: this.robotSphere.quaternion.toArray(),
      robotColour: this.robotMaterial.color.getHex(),
      robotEmissive: this.robotMaterial.emissive.getHex(),
      trailPoints: this.trailPoints.map((point) => point.toArray()),
      hasImpactMarker: this.hasImpactMarker,
      goalEmissiveIntensity: this.goalMarker?.material.emissiveIntensity ?? 0.62,
    };
  }

  restoreSession(snapshot) {
    if (!this.level || !snapshot?.state) return false;
    this.cancelDrag();
    this.cancelMotion("Level recovery");
    this.placed = Boolean(snapshot.placed);
    this.startPose = this.placed && snapshot.startPose ? { ...snapshot.startPose } : null;
    this.state = { ...snapshot.state };
    this.collisions = Math.max(0, Number(snapshot.collisions) || 0);
    this.matrix = Array.isArray(snapshot.matrix) ? [...snapshot.matrix] : new Array(64).fill("#000000");
    if (Array.isArray(snapshot.robotQuaternion) && snapshot.robotQuaternion.length === 4) {
      this.robotSphere.quaternion.fromArray(snapshot.robotQuaternion);
    } else {
      this.robotSphere.quaternion.identity();
    }
    this.robotMaterial.color.setHex(Number(snapshot.robotColour) || 0x59bfff);
    this.robotMaterial.emissive.setHex(Number(snapshot.robotEmissive) || 0x082f4d);
    this.trailPoints = Array.isArray(snapshot.trailPoints)
      ? snapshot.trailPoints.map((point) => new THREE.Vector3().fromArray(point))
      : [];
    this.updateTrailGeometry();
    this.hasImpactMarker = Boolean(snapshot.hasImpactMarker ?? snapshot.collisionMarkerVisible);
    this.collisionMarker.visible = this.visualSettings.showImpactMarkers && this.hasImpactMarker;
    if (this.goalMarker) this.goalMarker.material.emissiveIntensity = Number(snapshot.goalEmissiveIntensity) || 0.62;
    this.fixedAccumulator = 0;
    this.updateRobotTransform();
    this.emitCallback("onPlacement", this.placed, this.startPose ? { ...this.startPose } : null);
    this.emitTelemetry();
    return true;
  }

  returnToTray() {
    if (!this.level) return;
    this.placed = false;
    this.startPose = null;
    this.state = createRobotState(this.level, {
      ...this.level.tray,
      heading: this.level.start.heading,
    });
    this.robotSphere.quaternion.identity();
    this.clearTrail();
    this.hasImpactMarker = false;
    this.collisionMarker.visible = false;
    this.updateRobotTransform();
    this.emitCallback("onPlacement", false, null);
    this.emitTelemetry();
  }

  reset(keepPlaced = true) {
    this.cancelMotion("Reset");
    this.collisions = 0;
    this.hasImpactMarker = false;
    this.collisionMarker.visible = false;
    this.goalMarker && (this.goalMarker.material.emissiveIntensity = 0.62);
    this.clearTrail();
    if (keepPlaced && this.placed) this.placeOnStart(this.startPose);
    else this.returnToTray();
  }

  beginAttempt() {
    if (!this.placed) throw new Error("Place the robot on START before running code.");
    this.cancelMotion("New attempt");
    this.clearTrail();
    this.collisions = 0;
    this.hasImpactMarker = false;
    this.collisionMarker.visible = false;
    this.state = createRobotState(this.level, this.startPose || this.level.start);
    this.robotSphere.quaternion.identity();
    this.updateRobotTransform();
    this.recordTrail(true);
    this.emitTelemetry();
  }

  async executeRpc(method, args) {
    if (!this.placed) throw new Error("Robot is not on START.");
    if (this.state.goalReached && !method.startsWith("get_")) return null;
    const numeric = (index, fallback = 0) => {
      const value = Number(args[index]);
      return Number.isFinite(value) ? value : fallback;
    };

    switch (method) {
      case "roll": {
        this.state.heading = applyHeadingOffset(this.state.heading, numeric(0));
        this.state.speed = clampSpeed(numeric(1));
        this.updateRobotTransform();
        try {
          await this.runMotion(durationSteps(numeric(2)), () => this.advanceOneStep());
        } finally {
          this.state.speed = 0;
          this.emitTelemetry();
        }
        if (!this.state.goalReached) await this.runUntilStopped();
        return null;
      }
      case "spin": {
        this.state.speed = 0;
        await this.runUntilStopped();
        const start = this.state.heading;
        const degrees = numeric(0);
        const steps = Math.max(1, durationSteps(numeric(1, 0.5)));
        let index = 0;
        await this.runMotion(steps, () => {
          index += 1;
          this.state.heading = applyHeadingOffset(start, degrees * (index / steps));
          this.advanceOneStep();
        });
        return null;
      }
      case "wait":
        await this.runMotion(durationSteps(numeric(0)), () => this.advanceOneStep());
        return null;
      case "set_heading":
        this.state.heading = applyHeadingOffset(this.state.heading, numeric(0));
        this.updateRobotTransform();
        this.emitTelemetry();
        return null;
      case "set_speed":
        this.state.speed = clampSpeed(numeric(0));
        this.emitTelemetry();
        return null;
      case "stop_roll":
        this.state.speed = 0;
        await this.runUntilStopped();
        return null;
      case "set_main_led":
        this.setLed(...args);
        return null;
      case "set_matrix_pixel":
        this.setMatrixPixel(numeric(0), numeric(1), args[2]);
        return null;
      case "clear_matrix":
        this.matrix.fill("#000000");
        return null;
      case "get_heading": return this.state.heading;
      case "get_speed": return Math.round(this.state.actualSpeed);
      case "get_location_x": return Math.round(this.state.x * 10) / 10;
      case "get_location_y": return Math.round(this.state.z * 10) / 10;
      default: throw new Error(`Robot command is not allowed: ${method}`);
    }
  }

  advanceOneStep() {
    const before = this.state;
    const advanced = advanceState(this.level, before);
    const movedState = isPositionAllowed(this.level, advanced.x, advanced.z)
      ? advanced
      : {
        ...advanced,
        x: before.x,
        z: before.z,
        actualSpeed: 0,
        velocityX: 0,
        velocityZ: 0,
        collided: true,
        collision: true,
        collisions: Math.max(before.collisions || 0, advanced.collisions || 0) + 1,
        collisionNormalX: 0,
        collisionNormalZ: 0,
        distance: 0,
        movementX: 0,
        movementZ: 0,
      };
    const after = {
      ...movedState,
      goalReached: isStoppedAtGoal(this.level, movedState),
    };
    if (after.collision) {
      this.collisions = after.collisions;
      this.collisionMarker.position.set(after.x, this.level.baseTop + 2.4, after.z);
      this.hasImpactMarker = true;
      this.collisionMarker.visible = this.visualSettings.showImpactMarkers;
      this.emitCallback("onCollision", this.collisions, {
        x: after.x,
        z: after.z,
        normalX: after.collisionNormalX,
        normalZ: after.collisionNormalZ,
      });
    }
    this.state = after;
    this.rollSphere(after.movementX, after.movementZ);
    this.updateRobotTransform();
    this.recordTrail();
    this.emitTelemetry();
    if (after.goalReached && !before.goalReached) {
      this.goalMarker.material.emissiveIntensity = 2.4;
      this.emitCallback("onGoal");
      if (this.motion) this.motion.stepsRemaining = 0;
    }
  }

  runMotion(steps, tick) {
    if (steps <= 0 || this.state.goalReached) return Promise.resolve();
    if (this.motion) return Promise.reject(new Error("A robot motion is already active."));
    return new Promise((resolve, reject) => {
      this.motion = { stepsRemaining: steps, tick, resolve, reject };
      this.fixedAccumulator = 0;
    });
  }

  runUntilStopped(maximumSeconds = 1) {
    const physics = physicsForLevel(this.level);
    this.state.speed = 0;
    if (Math.hypot(this.state.velocityX, this.state.velocityZ) <= physics.stopVelocity) {
      this.advanceOneStep();
      return Promise.resolve();
    }
    return this.runMotion(durationSteps(maximumSeconds), () => {
      this.advanceOneStep();
      if (this.state.actualSpeed <= physics.stopVelocity / 0.625 && this.motion) {
        this.state.velocityX = 0;
        this.state.velocityZ = 0;
        this.state.actualSpeed = 0;
        this.motion.stepsRemaining = 0;
      }
    });
  }

  cancelMotion(reason = "Stopped") {
    this.state.speed = 0;
    this.state.actualSpeed = 0;
    this.state.velocityX = 0;
    this.state.velocityZ = 0;
    if (!this.motion) {
      this.emitTelemetry();
      return;
    }
    const motion = this.motion;
    this.motion = null;
    motion.reject(new Error(reason));
  }

  rollSphere(movementX, movementZ) {
    if (this.isReducedMotionActive()) return;
    const roll = rollingTransformForMovement(movementX, movementZ, this.level.robotRadius);
    if (!roll) return;
    const axis = new THREE.Vector3(roll.axisX, 0, roll.axisZ);
    const delta = new THREE.Quaternion().setFromAxisAngle(axis, roll.angle);
    this.robotSphere.quaternion.premultiply(delta);
  }

  updateRobotTransform() {
    this.robot.position.set(this.state.x, this.robotY, this.state.z);
    this.headingMarker.rotation.y = -this.state.heading * Math.PI / 180;
  }

  setLed(value, green, blue) {
    const colour = new THREE.Color(0x59bfff);
    if ([value, green, blue].every((channel) => Number.isFinite(Number(channel)))) {
      colour.setRGB(
        Math.max(0, Math.min(255, Number(value))) / 255,
        Math.max(0, Math.min(255, Number(green))) / 255,
        Math.max(0, Math.min(255, Number(blue))) / 255,
        THREE.SRGBColorSpace,
      );
    } else if (typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value)) {
      colour.set(value);
    }
    this.robotMaterial.color.copy(colour);
    this.robotMaterial.emissive.copy(colour).multiplyScalar(0.18);
  }

  setMatrixPixel(x, y, value) {
    const column = Math.max(0, Math.min(7, Math.round(x)));
    const row = Math.max(0, Math.min(7, Math.round(y)));
    this.matrix[row * 8 + column] = typeof value === "string" ? value : "#ffffff";
  }

  recordTrail(force = false) {
    const point = new THREE.Vector3(this.state.x, this.level.baseTop + 3.3, this.state.z);
    const previous = this.trailPoints.at(-1);
    if (!force && previous && previous.distanceToSquared(point) < 8) return;
    this.trailPoints.push(point);
    if (this.trailPoints.length > 900) this.trailPoints.shift();
    this.updateTrailGeometry();
  }

  clearTrail() {
    this.trailPoints = [];
    this.updateTrailGeometry();
  }

  updateTrailGeometry() {
    const positions = new Float32Array(this.trailPoints.length * 3);
    this.trailPoints.forEach((point, index) => {
      positions[index * 3] = point.x;
      positions[index * 3 + 1] = point.y;
      positions[index * 3 + 2] = point.z;
    });
    this.trailGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.trailGeometry.computeBoundingSphere();
  }

  emitTelemetry() {
    this.emitCallback("onTelemetry", {
      heading: Math.round(this.state.heading),
      speed: Math.round(this.state.actualSpeed),
      commandedSpeed: Math.round(this.state.speed),
      collisions: this.collisions,
      x: Math.round(this.state.x),
      z: Math.round(this.state.z),
    });
  }

  animate(time) {
    requestAnimationFrame(this.animate);
    const deltaSeconds = Math.min(0.1, Math.max(0, (time - this.lastFrameTime) / 1000));
    this.lastFrameTime = time;
    this.updateIdleRotation(time);
    this.controls.update(deltaSeconds);

    if (this.motion) {
      this.fixedAccumulator += deltaSeconds;
      let ticks = 0;
      while (this.motion && this.fixedAccumulator >= FIXED_STEP_SECONDS && ticks < MAX_TICKS_PER_FRAME) {
        const motion = this.motion;
        this.fixedAccumulator -= FIXED_STEP_SECONDS;
        try {
          motion.tick();
          motion.stepsRemaining -= 1;
          if (motion.stepsRemaining <= 0) {
            this.motion = null;
            motion.resolve();
          }
        } catch (error) {
          this.motion = null;
          motion.reject(error);
        }
        ticks += 1;
      }
    }

    if (this.startMarker && this.goalMarker) {
      const reducedMotion = this.isReducedMotionActive();
      const pulse = reducedMotion ? 0.65 : 0.65 + Math.sin(time * 0.004) * 0.18;
      this.startMarker.material.opacity = pulse;
      if (!this.state.goalReached) {
        this.goalMarker.material.opacity = reducedMotion ? 0.66 : 0.66 + Math.sin(time * 0.005 + 1) * 0.18;
      }
    }
    this.renderer.render(this.scene, this.camera);
  }

  resize() {
    const bounds = this.canvas.parentElement.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    this.camera.aspect = bounds.width / bounds.height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(bounds.width, bounds.height, false);
  }
}

function createLabel(text, foreground, background) {
  const canvas = document.createElement("canvas");
  canvas.width = 384;
  canvas.height = 96;
  const context = canvas.getContext("2d");
  context.fillStyle = background;
  roundedRect(context, 5, 5, 374, 86, 22);
  context.fill();
  context.fillStyle = foreground;
  context.font = "800 34px system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 192, 49);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.scale.set(128, 32, 1);
  return sprite;
}

function roundedRect(context, x, y, width, height, radius) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
}

function disposeObject3D(root) {
  if (!root) return;
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  root.traverse((object) => {
    if (object.geometry?.dispose) geometries.add(object.geometry);
    const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of objectMaterials) {
      if (!material?.dispose) continue;
      materials.add(material);
      for (const value of Object.values(material)) if (value?.isTexture && value.dispose) textures.add(value);
    }
  });
  for (const texture of textures) texture.dispose();
  for (const material of materials) material.dispose();
  for (const geometry of geometries) geometry.dispose();
  root.clear();
}
