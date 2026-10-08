import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const pairs = JSON.parse(fs.readFileSync(path.join(root, 'tests/layout/move_map.json'), 'utf8')).moves;
const ordered = [...pairs].sort((a, b) => b[0].length - a[0].length);
const reverse = [...pairs].sort((a, b) => b[1].length - a[1].length);
const slash = value => value.split(path.sep).join('/');
function relocate(relative, inverse = false) {
  for (const pair of inverse ? reverse : ordered) {
    const [before, after] = inverse ? [pair[1], pair[0]] : pair;
    if (relative === before || relative.startsWith(before + '/')) return after + relative.slice(before.length);
  }
  return relative;
}
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const matcher = new RegExp('(?<![A-Za-z0-9_/])(' + ordered.map(pair => escape(pair[0])).join('|') + ')(?=/|[\\s`\'"\\)]|$)', 'g');
const lookup = new Map(pairs);
const files = [path.join(root, 'README.md'), path.join(root, '需求说明.md')];
function collect(folder) {
  for (const item of fs.readdirSync(folder, {withFileTypes: true})) {
    if (item.isSymbolicLink() || ['vendor', 'slprj', 'simrt_build_evidence'].includes(item.name) || item.name.endsWith('_ert_rtw')) continue;
    const file = path.join(folder, item.name);
    if (item.isDirectory()) collect(file);
    else if (item.name.endsWith('.md')) files.push(file);
  }
}
for (const relative of ['docs', 'tests/validation', 'toolchain/simrt_linux_target', 'linux']) collect(path.join(root, relative));
const changed = [];
for (const file of files) {
  const text = fs.readFileSync(file, 'utf8');
  const oldFile = path.join(root, relocate(slash(path.relative(root, file)), true));
  const links = [];
  let updated = text.replace(/\[([^\]\n]+)\]\(([^)\n]+)\)/g, (original, label, target) => {
    let value = target;
    if (!/^(?:https?:|mailto:|#)/i.test(target)) {
      const [plain, anchor] = target.replace(/^<|>$/g, '').split('#', 2);
      if (!/^[A-Za-z]:/.test(plain)) {
        const relative = slash(path.relative(root, path.resolve(path.dirname(oldFile), plain)));
        const destination = path.join(root, relocate(relative));
        if (!relative.startsWith('../')) value = slash(path.relative(path.dirname(file), destination)) + (anchor ? '#' + anchor : '');
      }
    }
    links.push(`[${label}](${value})`);
    return `@@SIMRT_LINK_${links.length - 1}@@`;
  });
  updated = updated.replace(matcher, before => lookup.get(before));
  updated = updated.replace(/@@SIMRT_LINK_(\d+)@@/g, (_, index) => links[Number(index)]);
  if (updated !== text) { fs.writeFileSync(file, updated); changed.push(slash(path.relative(root, file))); }
}
fs.writeFileSync(path.join(root, 'tests/layout/doc_paths_updated.json'), JSON.stringify(changed, null, 2) + '\n');
console.log(`Updated ${changed.length} documentation files.`);
