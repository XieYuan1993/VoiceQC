const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/knowledge-trigger-highlights.ts"), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const api = {};
new Function("exports", output)(api);

test("highlights Chinese triggers and merges overlaps", () => {
  assert.deepEqual(api.knowledgeTriggerRanges("需要正本收據", ["正本", "正本收據", "收據"]), [[2, 6]]);
});

test("handles English case and spacing", () => {
  assert.deepEqual(api.knowledgeTriggerRanges("使用qrCode或FPS", ["QR code", "FPS"]), [[2, 8], [9, 12]]);
});

test("preserves source offsets for formatted numbers", () => {
  assert.deepEqual(api.knowledgeTriggerRanges("保障1,000元", ["1000"]), [[2, 7]]);
});

test("does not mark larger numbers or English substrings", () => {
  assert.deepEqual(api.knowledgeTriggerRanges("10000 happy APP", ["1000", "App"]), [[12, 15]]);
});

test("escapes punctuation instead of treating trigger words as regex", () => {
  assert.deepEqual(api.knowledgeTriggerRanges("(FPS) a+b", ["(FPS)", "a+b"]), [[0, 5], [6, 9]]);
});

test("empty terms and missing terms produce no highlight", () => {
  assert.deepEqual(api.knowledgeTriggerRanges("早晨", ["", "  ", "FPS"]), []);
});
