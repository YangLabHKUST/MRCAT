// Run with node tests/test_result_formatters.cjs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../mrcat/web/static/app.js"), "utf8");
const context = vm.createContext({});
for (const name of ["text", "formatEstimate", "formatPValue"]) {
  const match = source.match(new RegExp(`^function ${name}\\([^]*?^\\}`, "m"));
  assert.ok(match, `${name} must exist`);
  vm.runInContext(match[0], context);
}

for (const missing of [null, undefined, ""]) {
  assert.equal(context.formatPValue(missing), "-");
  assert.equal(context.formatEstimate(missing), "-");
}
assert.equal(context.formatPValue("<0.074"), "<0.074");
assert.equal(context.formatPValue("<0.001"), "<0.001");
assert.equal(context.formatPValue(0.05), "0.05");
assert.equal(context.formatEstimate(0), "0");
console.log("PASS: missing results remain unavailable and bounded P values retain inequalities.");

const forestSource = fs.readFileSync(path.join(__dirname, "../mrcat/web/static/replication-forest.js"), "utf8");
for (const name of ["replicationForestNumber", "replicationForestInterval"]) {
  const match = forestSource.match(new RegExp(`^function ${name}\\([^]*?^\\}`, "m"));
  assert.ok(match, `${name} must exist`);
  vm.runInContext(match[0], context);
}
assert.equal(context.replicationForestInterval({ "beta.hat": .21, se: .1 }), null);
const recorded = context.replicationForestInterval({
  "beta.hat": .21, se: .1, ci: { level: .95, ranges: [{ lower: -.02, upper: .44 }] },
});
assert.equal(recorded.lower, -.02);
assert.equal(recorded.upper, .44);
console.log("PASS: forest intervals come from saved bounds; missing intervals remain unavailable.");
