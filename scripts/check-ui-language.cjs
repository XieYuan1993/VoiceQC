// Check authored UI copy; multilingual business vocabularies remain unchanged.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('../apps/web/node_modules/typescript');
const root = path.resolve(__dirname, '../apps/web/src');
const allowed = new Map([
  ['lib/supervisor-notification.ts', 'phrases'],
  ['app/(dashboard)/settings/app-settings-section.tsx', 'ORDER_STATUS_OPTIONS'],
  ['app/(dashboard)/transactions/import-wizard.tsx', 'TEMPLATE_EXAMPLES'],
]);
function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? files(file) : /\.tsx?$/.test(file) ? [file] : [];
  });
}
let checked = 0;
const errors = [];
for (const file of files(root)) {
  const relative = path.relative(root, file).replaceAll('\\', '/');
  const ast = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
  function visit(node) {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ||
        ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node) || ts.isJsxText(node)) {
      checked++;
      if (/\p{Script=Han}/u.test(node.text)) {
        let parent = node.parent;
        while (parent && !ts.isVariableDeclaration(parent)) parent = parent.parent;
        if (!parent || parent.name.getText(ast) !== allowed.get(relative)) {
          errors.push(`${relative}:${ast.getLineAndCharacterOfPosition(node.getStart(ast)).line + 1}: ${node.text.trim().slice(0, 100)}`);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
}
if (errors.length) {
  console.error(errors.join('\n'));
  process.exitCode = 1;
} else console.log(`English UI check passed (${checked} text fragments; business-language literals excluded).`);
