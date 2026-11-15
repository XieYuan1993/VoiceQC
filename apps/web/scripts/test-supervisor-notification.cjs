const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const api = {};
new Function("exports", ts.transpileModule(fs.readFileSync(path.join(__dirname, "../src/lib/supervisor-notification.ts"), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(api);
test("S01 Cantonese service dissatisfaction and supervisor request", () => {
  assert.ok(api.complaintTrigger("點解你哋嘅服務咁差"));
  assert.ok(api.complaintTrigger("我要搵你主管"));
});
test("S13 Mandarin strong dissatisfaction", () => {
  assert.ok(api.complaintTrigger("我非常的不高兴"));
  assert.ok(api.complaintTrigger("我非常的不滿"));
});
test("ordinary enquiries and negated complaint do not trigger", () => {
  assert.equal(api.complaintTrigger("理賠文件交咗未？"), null);
  assert.equal(api.complaintTrigger("我不想投诉你"), null);
});
test("both delivery channels default off", () => {
  assert.equal(api.emptySupervisor.email_enabled, false);
  assert.equal(api.emptySupervisor.sms_enabled, false);
});
