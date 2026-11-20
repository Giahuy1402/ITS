const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = new Proxy({}, {get: () => () => {}});
const canvas = {width: 1000, height: 500, getContext: () => context,
    addEventListener() {}, getBoundingClientRect: () => ({left: 0, top: 0, width: 1000, height: 500})};
const elements = new Map();
function element(id) {
    if (!elements.has(id)) elements.set(id, {value: "10", checked: false, style: {}, disabled: false,
        scrollIntoView() {}, play() {return Promise.resolve();}, pause() {}, load() {}, removeAttribute() {}});
    return elements.get(id);
}
const sandbox = {API_BASE_URL: "http://localhost", Image: class {}, requestAnimationFrame: () => 1, cancelAnimationFrame() {}, window: {addEventListener() {}},
    document: {addEventListener() {}, getElementById: id => id === "canvas" ? canvas : element(id),
        querySelector: () => element("video-stage"), querySelectorAll: () => [{value: "2", checked: true}]}, alert: message => sandbox.alerts.push(message), alerts: [],
    TrafficVisionAPI: {startSession: async payload => {sandbox.payload = payload; throw Error("stop after capture");}}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../frontend/js/canvas_editor.js"), "utf8"), sandbox);
vm.runInContext("globalThis.editor = new SetupCanvasEditor('canvas'); editor.bgLoaded = true;", sandbox);
const editor = sandbox.editor;
const event = (x, y) => ({clientX: x, clientY: y, button: 0});
function click(x, y) {editor.handleMouseDown(event(x, y)); editor.handleMouseUp(event(x, y));}
editor.setTool("line_a");
click(250, 150);
assert.equal(editor.getConfig().line_a, null, "one click must not create a zero-length line");
assert.equal(editor.dragState.waiting, true);
click(250, 150);
assert.equal(editor.getConfig().line_a, null, "repeated click at the same point stays pending");
editor.handleMouseMove(event(750, 150));
click(750, 150);
assert.equal(editor.lineA.p1.x, 0.25);
assert.equal(editor.lineA.p2.x, 0.75);
assert.equal(editor.dragState, null);
editor.setTool("line_b");
editor.handleMouseDown(event(250, 325));
editor.handleMouseMove(event(750, 325));
editor.handleMouseUp(event(750, 325));
assert.equal(editor.lineB.p1.y, 0.65);
assert.equal(editor.lineB.p2.x, 0.75);
const previous = editor.lineB;
click(400, 300);
assert.equal(editor.lineB, previous, "a short press must not overwrite a valid line");
editor.setTool("count");
assert.equal(editor.dragState, null, "changing tool cancels an unfinished line");
click(100, 100);
editor.clearAll();
assert.equal(editor.dragState, null);
const collapsed = {p1: {x: 0.5, y: 0.5}, p2: {x: 0.5, y: 0.5}};
editor.loadConfig({line_a: collapsed, line_b: collapsed, count_line: collapsed});
assert.equal(editor.lineA, null);
assert.equal(editor.lineB, null);
assert.equal(editor.countLine, null);
editor.lineA = collapsed;
assert.equal(editor.getConfig().line_a, null, "invalid old state cannot enter a payload");
vm.runInContext(fs.readFileSync(path.join(__dirname, "../frontend/js/app.js"), "utf8"), sandbox);
vm.runInContext("selectedVideo = {id: 1, fps: 30, filename: 'sample.mp4'}; canvasEditor = editor; resetResults = () => {};", sandbox);
(async () => {
    element("input-distance-m").value = "";
    await vm.runInContext("startAnalysisSession()", sandbox);
    assert.equal(sandbox.payload.speed_calibration.enabled, false);
    assert.equal(sandbox.payload.speed_calibration.line_a, null);
    assert.equal(sandbox.payload.speed_calibration.line_b, null);
    assert.equal(sandbox.payload.speed_calibration.distance_meters, 10);
    sandbox.payload = null;
    element("chk-enable-speed").checked = true;
    editor.setTool("line_a");
    click(300, 100);
    await vm.runInContext("startAnalysisSession()", sandbox);
    assert.equal(sandbox.payload, null, "unfinished enabled lines must be stopped before the API");
    assert.ok(sandbox.alerts.at(-1).includes("chưa hoàn tất"));
    console.log("Canvas regression checks passed: click, drag, pending lines, old presets, disabled payload.");
})().catch(error => {console.error(error); process.exitCode = 1;});
