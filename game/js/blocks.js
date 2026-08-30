const Blockly = window.Blockly;
const pythonBundle = window.python;

if (!Blockly || !pythonBundle?.pythonGenerator) {
  throw new Error("The local Blockly and Python generator bundles did not load.");
}

const PY = pythonBundle.pythonGenerator;
const ORDER = pythonBundle.Order || {};
const ORDER_NONE = ORDER.NONE ?? PY.ORDER_NONE ?? 99;
const ORDER_ATOMIC = ORDER.ATOMIC ?? PY.ORDER_ATOMIC ?? 0;

const COLOURS = Object.freeze({ drive: 205, looks: 292, sense: 28 });

export const SPHERO_BLOCK_TYPES = Object.freeze([
  "sphero_roll",
  "sphero_spin",
  "sphero_wait",
  "sphero_set_heading",
  "sphero_set_speed",
  "sphero_stop",
  "sphero_set_main_led",
  "sphero_set_matrix_pixel",
  "sphero_clear_matrix",
  "sphero_get_heading",
  "sphero_get_speed",
  "sphero_get_location_x",
  "sphero_get_location_y",
]);

Blockly.defineBlocksWithJsonArray([
  {
    type: "sphero_roll",
    message0: "roll %1° from facing, speed %2 for %3 seconds",
    args0: [
      { type: "input_value", name: "HEADING", check: "Number" },
      { type: "input_value", name: "SPEED", check: "Number" },
      { type: "input_value", name: "SECONDS", check: "Number" },
    ],
    inputsInline: true,
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.drive,
    tooltip: "Turn from the sphere's current direction, then roll. Use 0° for forward, +90° for right, and -90° for left.",
  },
  {
    type: "sphero_spin",
    message0: "spin %1° over %2 seconds",
    args0: [
      { type: "input_value", name: "DEGREES", check: "Number" },
      { type: "input_value", name: "SECONDS", check: "Number" },
    ],
    inputsInline: true,
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.drive,
    tooltip: "Brake, then rotate in place. Positive angles turn right.",
  },
  {
    type: "sphero_wait",
    message0: "wait %1 seconds",
    args0: [{ type: "input_value", name: "SECONDS", check: "Number" }],
    inputsInline: true,
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.drive,
    tooltip: "Wait while the current speed and heading continue.",
  },
  {
    type: "sphero_set_heading",
    message0: "turn instantly by %1°",
    args0: [{ type: "input_value", name: "HEADING", check: "Number" }],
    inputsInline: true,
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.drive,
    tooltip: "Turn by an angle from the sphere's current direction without advancing simulation time.",
  },
  {
    type: "sphero_set_speed",
    message0: "set speed %1",
    args0: [{ type: "input_value", name: "SPEED", check: "Number" }],
    inputsInline: true,
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.drive,
    tooltip: "Set speed from 0 to 255.",
  },
  {
    type: "sphero_stop",
    message0: "stop",
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.drive,
    tooltip: "Actively brake the rolling robot to a stop.",
  },
  {
    type: "sphero_set_main_led",
    message0: "set main LED %1",
    args0: [{ type: "input_value", name: "COLOUR", check: "Colour" }],
    inputsInline: true,
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.looks,
    tooltip: "Change the sphere robot's main colour.",
  },
  {
    type: "sphero_set_matrix_pixel",
    message0: "set matrix pixel x %1 y %2 to %3",
    args0: [
      { type: "input_value", name: "X", check: "Number" },
      { type: "input_value", name: "Y", check: "Number" },
      { type: "input_value", name: "COLOUR", check: "Colour" },
    ],
    inputsInline: true,
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.looks,
    tooltip: "Set one virtual 8×8 matrix pixel.",
  },
  {
    type: "sphero_clear_matrix",
    message0: "clear matrix",
    previousStatement: null,
    nextStatement: null,
    colour: COLOURS.looks,
    tooltip: "Turn every virtual matrix pixel off.",
  },
  {
    type: "sphero_get_heading",
    message0: "current world bearing °",
    output: "Number",
    colour: COLOURS.sense,
    tooltip: "Read the sphere's current world bearing, measured clockwise from world north.",
  },
  {
    type: "sphero_get_speed",
    message0: "current speed",
    output: "Number",
    colour: COLOURS.sense,
    tooltip: "Read the current speed.",
  },
  {
    type: "sphero_get_location_x",
    message0: "position x mm",
    output: "Number",
    colour: COLOURS.sense,
    tooltip: "Read the east/west position in millimetres.",
  },
  {
    type: "sphero_get_location_y",
    message0: "position z mm",
    output: "Number",
    colour: COLOURS.sense,
    tooltip: "Read the north/south position in millimetres.",
  },
]);

function value(block, generator, name, fallback = "0") {
  return generator.valueToCode(block, name, ORDER_NONE) || fallback;
}

PY.forBlock.sphero_roll = (block, generator) =>
  `await roll(${value(block, generator, "HEADING")}, ${value(block, generator, "SPEED")}, ${value(block, generator, "SECONDS")})\n`;
PY.forBlock.sphero_spin = (block, generator) =>
  `await spin(${value(block, generator, "DEGREES")}, ${value(block, generator, "SECONDS")})\n`;
PY.forBlock.sphero_wait = (block, generator) =>
  `await wait(${value(block, generator, "SECONDS")})\n`;
PY.forBlock.sphero_set_heading = (block, generator) =>
  `await set_heading(${value(block, generator, "HEADING")})\n`;
PY.forBlock.sphero_set_speed = (block, generator) =>
  `await set_speed(${value(block, generator, "SPEED")})\n`;
PY.forBlock.sphero_stop = () => "await stop_roll()\n";
PY.forBlock.sphero_set_main_led = (block, generator) =>
  `await set_main_led(${value(block, generator, "COLOUR", "'#59bfff'")})\n`;
PY.forBlock.sphero_set_matrix_pixel = (block, generator) =>
  `await set_matrix_pixel(${value(block, generator, "X")}, ${value(block, generator, "Y")}, ${value(block, generator, "COLOUR", "'#ffffff'")})\n`;
PY.forBlock.sphero_clear_matrix = () => "await clear_matrix()\n";
PY.forBlock.sphero_get_heading = () => ["(await get_heading())", ORDER_ATOMIC];
PY.forBlock.sphero_get_speed = () => ["(await get_speed())", ORDER_ATOMIC];
PY.forBlock.sphero_get_location_x = () => ["(await get_location_x())", ORDER_ATOMIC];
PY.forBlock.sphero_get_location_y = () => ["(await get_location_y())", ORDER_ATOMIC];

export const TOOLBOX = {
  kind: "categoryToolbox",
  contents: [
    {
      kind: "category",
      name: "Drive",
      colour: String(COLOURS.drive),
      contents: [
        blockWithNumbers("sphero_roll", { HEADING: 0, SPEED: 160, SECONDS: 1 }),
        blockWithNumbers("sphero_spin", { DEGREES: 90, SECONDS: 0.5 }),
        blockWithNumbers("sphero_wait", { SECONDS: 1 }),
        blockWithNumbers("sphero_set_heading", { HEADING: 0 }),
        blockWithNumbers("sphero_set_speed", { SPEED: 160 }),
        { kind: "block", type: "sphero_stop" },
      ],
    },
    {
      kind: "category",
      name: "Lights",
      colour: String(COLOURS.looks),
      contents: [
        blockWithColour("sphero_set_main_led", "COLOUR", "#59bfff"),
        {
          kind: "block",
          type: "sphero_set_matrix_pixel",
          inputs: {
            X: numberShadow(3),
            Y: numberShadow(3),
            COLOUR: colourShadow("#ffd65a"),
          },
        },
        { kind: "block", type: "sphero_clear_matrix" },
      ],
    },
    {
      kind: "category",
      name: "Sensors",
      colour: String(COLOURS.sense),
      contents: SPHERO_BLOCK_TYPES.slice(9).map((type) => ({ kind: "block", type })),
    },
    { kind: "sep" },
    {
      kind: "category",
      name: "Logic",
      colour: "210",
      contents: ["controls_if", "logic_compare", "logic_operation", "logic_negate", "logic_boolean"]
        .map((type) => ({ kind: "block", type })),
    },
    {
      kind: "category",
      name: "Loops",
      colour: "120",
      contents: [
        blockWithNumbers("controls_repeat_ext", { TIMES: 4 }),
        { kind: "block", type: "controls_whileUntil" },
      ],
    },
    {
      kind: "category",
      name: "Math",
      colour: "230",
      contents: ["math_number", "math_arithmetic", "math_round"]
        .map((type) => ({ kind: "block", type })),
    },
    {
      kind: "category",
      name: "Variables",
      colour: "330",
      custom: "VARIABLE",
    },
  ],
};

function numberShadow(number) {
  return { shadow: { type: "math_number", fields: { NUM: number } } };
}

function colourShadow(colour) {
  return { shadow: { type: "colour_picker", fields: { COLOUR: colour } } };
}

function blockWithNumbers(type, values) {
  return {
    kind: "block",
    type,
    inputs: Object.fromEntries(Object.entries(values).map(([name, number]) => [name, numberShadow(number)])),
  };
}

function blockWithColour(type, name, colour) {
  return { kind: "block", type, inputs: { [name]: colourShadow(colour) } };
}

export function createWorkspace(container) {
  return Blockly.inject(container, {
    toolbox: TOOLBOX,
    renderer: "zelos",
    media: "./vendor/blockly/media/",
    grid: { spacing: 22, length: 3, colour: "#c5d8df", snap: true },
    zoom: { controls: true, wheel: true, startScale: 0.84, maxScale: 1.4, minScale: 0.5, scaleSpeed: 1.1 },
    trashcan: true,
    move: { scrollbars: true, drag: true, wheel: true },
  });
}

export function createStarterProgram(workspace) {
  workspace.clear();
  // Give students a useful first move without revealing the turn or full route.
  const first = makeCommand(workspace, "sphero_roll", { HEADING: 0, SPEED: 160, SECONDS: 1 });
  first.moveBy(42, 42);
  workspace.cleanUp();
}

function makeCommand(workspace, type, values) {
  const block = workspace.newBlock(type);
  block.initSvg();
  block.render();
  for (const [inputName, number] of Object.entries(values)) {
    const numberBlock = workspace.newBlock("math_number");
    numberBlock.setFieldValue(String(number), "NUM");
    numberBlock.setShadow(true);
    numberBlock.initSvg();
    numberBlock.render();
    block.getInput(inputName).connection.connect(numberBlock.outputConnection);
  }
  return block;
}

export function generatePython(workspace) {
  const code = PY.workspaceToCode(workspace).trim();
  return `${code || "# Add blocks to create a program."}\n`;
}

export function saveBlocks(workspace) {
  return Blockly.serialization.workspaces.save(workspace);
}

export function loadBlocks(workspace, state) {
  workspace.clear();
  Blockly.serialization.workspaces.load(state, workspace);
}

export function validateBlocksState(state) {
  const workspace = new Blockly.Workspace();
  try {
    Blockly.serialization.workspaces.load(state, workspace);
    return true;
  } finally {
    workspace.dispose();
  }
}

export function isUiEvent(event) {
  return event.isUiEvent === true || event.type === Blockly.Events.VIEWPORT_CHANGE || event.type === Blockly.Events.TOOLBOX_ITEM_SELECT;
}

export { Blockly };
