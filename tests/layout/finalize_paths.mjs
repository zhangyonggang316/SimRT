import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const moves = JSON.parse(fs.readFileSync(path.join(root, 'tests/layout/move_map.json'), 'utf8')).moves;
const ordered = [...moves].sort((a, b) => b[0].length - a[0].length);
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const prefix = new RegExp('(D:/05SimRT/|\\./)(' + ordered.map(pair => escape(pair[0])).join('|') + ')(?=/|[\\s\'"`)]|$)', 'g');
const lookup = new Map(moves);
const changed = [];
function walk(folder, accept, transform) {
  for (const item of fs.readdirSync(folder, { withFileTypes: true })) {
    if (item.isSymbolicLink() || ['__pycache__', 'slprj', 'simrt_build_evidence'].includes(item.name) || item.name.endsWith('_ert_rtw')) continue;
    const file = path.join(folder, item.name);
    if (item.isDirectory()) walk(file, accept, transform);
    else if (accept(file)) {
      const before = fs.readFileSync(file, 'utf8');
      const after = transform(before);
      if (after !== before) { fs.writeFileSync(file, after); changed.push(path.relative(root, file)); }
    }
  }
}
const sharedPaths = text => text.replaceAll('app/qt_xcp_host/pyxcp_host', 'shared/python/pyxcp_host').replaceAll('app/python', 'shared/python');
for (const folder of ['docs', 'linux', 'toolchain/simrt_linux_target', 'tests/validation']) {
  walk(path.join(root, folder), file => file.endsWith('.md'), text => sharedPaths(text.replace(prefix, (_, start, old) => start + lookup.get(old))));
}
for (const folder of ['linux/tools', 'tests/tools/scripts']) {
  walk(path.join(root, folder), file => file.endsWith('.py'), text => text.replaceAll('app/qt_xcp_host', 'shared/python').replaceAll('app/python', 'shared/python'));
}
for (const name of ['tests/maintenance/clean_generated.ps1']) {
  const file = path.join(root, name);
  const before = fs.readFileSync(file, 'utf8');
  const after = sharedPaths(before);
  if (before !== after) { fs.writeFileSync(file, after); changed.push(name); }
}
fs.writeFileSync(path.join(root, 'tests/layout/final_paths_updated.json'), JSON.stringify(changed, null, 2) + '\n');
console.log(`Updated ${changed.length} path references.`);
