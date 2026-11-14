const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const source = fs.readFileSync(path.join(__dirname, "../src/app/(dashboard)/recordings/[id]/transcript-knowledge-hints.tsx"), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText;
const api = {};
new Function("exports", "require", output)(api, require);
const match = (code) => ({ card: { id: code, code, title: `Title ${code}`, content: { suggested_reply: "Full reply" } }, hits: [] });
const render = (matches) => renderToStaticMarkup(React.createElement(api.TranscriptKnowledgeHints, { matches, onSelect: () => {} }));

test("no hints render when no card matches", () => {
  assert.equal(render([]), "");
});

test("single card renders one amber entry without a large reply preview", () => {
  const html = render([match("K01")]);
  assert.equal((html.match(/<button /g) ?? []).length, 1);
  assert.ok(html.includes("bg-amber-50"));
  assert.ok(!html.includes("Full reply"));
  assert.ok(!html.includes("<details"));
});

test("multiple cards render a collapsed native chooser and full labels", () => {
  const html = render([match("K01"), match("K02")]);
  assert.equal((html.match(/<summary /g) ?? []).length, 1);
  assert.ok(html.includes("2 張卡片"));
  assert.ok(html.includes("Title K01") && html.includes("Title K02"));
  assert.ok(!/<details[^>]*\sopen(?:[\s=>])/.test(html));
});
