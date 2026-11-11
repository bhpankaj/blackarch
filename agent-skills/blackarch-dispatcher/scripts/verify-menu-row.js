#!/usr/bin/env node
// Verify a menu row the way the shell will actually render it.
//
//   verify-menu-row.js <menu.jsonc> <row-id-or-label> [more...]
//
// Loads the real shell/plugins/menu/MenuModel.js, so kind/parent/visibility
// answers match the running shell instead of a reimplementation. Exits 1 when
// any row is missing, has a bad parent, is a kind:"app" row carrying an
// `action` (which AppLibrary.launch would ignore), or is not visible even when
// its own `when:` is true.

const fs = require("fs");
const path = require("path");

const BLACKARCH = process.env.BLACKARCH_PATH || "/opt/blackarch";

function loadModel() {
  const src = fs.readFileSync(
    path.join(BLACKARCH, "shell/plugins/menu/MenuModel.js"), "utf8");
  const mod = { exports: {} };
  new Function("module", "exports", src)(mod, mod.exports);
  return mod.exports;
}

function main() {
  const [file, ...needles] = process.argv.slice(2);
  if (!file || needles.length === 0) {
    console.error("Usage: verify-menu-row.js <menu.jsonc> <row-id-or-label> [...]");
    process.exit(2);
  }

  const M = loadModel();
  const items = M.parseMenuJsonc(fs.readFileSync(file, "utf8"));
  const merged = M.mergeMenuSources(items, []);
  const map = merged.items;
  const order = merged.itemOrder;

  // guardScript() takes the id -> entry map, not the parsed array.
  const guardMap = {};
  for (const entry of items) guardMap[entry.id] = entry;

  let bad = 0;
  for (const needle of needles) {
    const row = map[needle] || items.find((e) => e.label === needle);
    if (!row) {
      console.log(`MISSING  ${needle}`);
      bad++;
      continue;
    }

    const parent = map[row.parent];
    const problems = [];
    if (!parent) {
      problems.push(`parent '${row.parent}' does not exist`);
    } else if (parent.kind !== "menu" && parent.kind !== "link") {
      problems.push(`parent '${row.parent}' is kind:${parent.kind}, not a menu`);
    }
    if (row.kind === "app" && row.action) {
      problems.push("kind:app ignores 'action' (launches via gtk-launch appId.desktop)");
    }

    const visTrue = M.isVisible(map, order, { [row.id]: true }, row);
    const visFalse = M.isVisible(map, order, { [row.id]: false }, row);
    if (!visTrue) problems.push("not visible even when its when: is true");

    console.log(`${problems.length ? "BAD  " : "OK   "} ${row.id}`);
    console.log(`     kind=${row.kind} parent=${row.parent} ` +
                `(${parent ? parent.kind : "MISSING"}) ` +
                `visible when=true:${visTrue} when=false:${visFalse}`);

    const guard = M.guardScript(guardMap).split("\n")
      .filter((line) => line.includes(row.id)).join("\n");
    if (guard) console.log(`     guard: ${guard}`);

    for (const problem of problems) {
      console.log(`     !! ${problem}`);
      bad++;
    }
  }

  process.exit(bad ? 1 : 0);
}

main();
