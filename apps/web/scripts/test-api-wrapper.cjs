const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

// Exercise the actual wrapper without a browser, backend or runtime TS loader.
const source = fs.readFileSync(path.join(__dirname, "../src/lib/api.ts"), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const api = {};
new Function("exports", output)(api);

for (const method of ["apiJson", "apiCall"]) {
  test(`${method} sends project scope, encoded path and false query values`, async (t) => {
    let request;
    t.mock.method(globalThis, "fetch", async (url, options) => {
      request = { url: new URL(url), options };
      return new Response(JSON.stringify({ answer: "Answer" }), { status: 200 });
    });
    const result = await api[method]("/api/knowledge-faqs/{id}", "get", {
      params: { path: { id: "faq /1" }, query: { project_id: "fwd-project", include_inactive: false, omit: undefined } },
    });
    assert.equal(request.url.pathname, "/api/knowledge-faqs/faq%20%2F1");
    assert.equal(request.url.searchParams.get("project_id"), "fwd-project");
    assert.equal(request.url.searchParams.get("include_inactive"), "false");
    assert.equal(request.url.searchParams.has("omit"), false);
    assert.equal(request.options.credentials, "include");
    assert.equal(result.answer, "Answer");
  });
}

test("apiJson scopes writes and preserves existing query parameters", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const parsed = new URL(url);
    assert.equal(parsed.searchParams.get("existing"), "1");
    assert.equal(parsed.searchParams.get("project_id"), "fwd-project");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { code: "K20" });
    return new Response("{}", { status: 200 });
  });
  await api.apiJson("/api/knowledge-cards?existing=1", "post", {
    params: { query: { project_id: "fwd-project" } }, body: { code: "K20" },
  });
});
