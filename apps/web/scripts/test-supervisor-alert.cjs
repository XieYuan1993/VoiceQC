const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const api = {};
const source = fs.readFileSync(path.join(__dirname, "../src/app/(dashboard)/recordings/[id]/supervisor-alert.tsx"), "utf8");
new Function("exports", "require", ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText)(api, (name) => name === "@/lib/api" ? {} : require(name));
test("inline warning has no popup or confirmation control", () => {
  const html = renderToStaticMarkup(React.createElement(api.SupervisorAlert, { active: false, contact: null, error: false }));
  assert.ok(html.includes("bg-red-50"));
  assert.ok(html.includes("到達此時間點後自動通知"));
  assert.ok(!html.includes("<button"));
  assert.ok(!html.includes('role="dialog"'));
});
test("unconfigured channels never report successful notification", () => {
  const html = renderToStaticMarkup(React.createElement(api.SupervisorAlert, { active: true, contact: { name: "", email_enabled: false, sms_enabled: false }, error: false }));
  assert.ok(html.includes("未啟用通知渠道"));
  assert.ok(!html.includes("已自動通知主管"));
});
