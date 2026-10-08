import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const files = ['README.md', '需求说明.md', 'app/README.md', 'shared/README.md', 'toolchain/README.md', 'linux/README.md', 'tests/README.md', 'demos/README.md'];
for (const item of fs.readdirSync(path.join(root, 'docs'))) if (item.endsWith('.md')) files.push('docs/' + item);
const missing = [];
for (const name of files) {
  const file = path.join(root, name);
  for (const match of fs.readFileSync(file, 'utf8').matchAll(/\[[^\]\n]*\]\(([^)\n]*)\)/g)) {
    const target = match[1].replace(/^<|>$/g, '').split('#')[0];
    if (!target || /^(https?:|mailto:)/i.test(target)) continue;
    if (!fs.existsSync(path.resolve(path.dirname(file), target))) missing.push({file:name, target});
  }
}
fs.writeFileSync(path.join(root, 'tests/layout/doc_links.json'), JSON.stringify({files:files.length, missing}, null, 2));
console.log(JSON.stringify(missing, null, 2));
