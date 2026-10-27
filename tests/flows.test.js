import test from 'node:test';
import assert from 'node:assert/strict';
import { nodes, scenarios, advance, allEdges } from '../src/flows.js';
test('every scenario has a continuous route from entry through verification to entry', () => {
  for (const scenario of scenarios) {
    assert.equal(scenario.steps[0].from, 'omp');
    assert.equal(scenario.steps.at(-1).from, 'verify');
    assert.equal(scenario.steps.at(-1).to, 'omp');
    scenario.steps.forEach((step, i) => {
      assert.ok(nodes[step.from] && nodes[step.to]);
      if (i) assert.equal(scenario.steps[i - 1].to, step.from);
    });
  }
});
test('local scenarios never visit cloud agents and retry passes verification again', () => {
  for (const scenario of scenarios.filter(s => s.route === 'LOCAL ONLY')) {
    assert.ok(scenario.steps.every(s => !['codex', 'claude'].includes(s.to)));
  }
  const retry = scenarios.find(s => s.id === 'retry').steps;
  const failure = retry.findIndex(s => s.kind === 'retry');
  assert.equal(retry[failure].from, 'verify');
  assert.equal(retry[failure + 1].to, 'verify');
});
test('advancing terminates exactly at the scenario boundary', () => {
  for (const scenario of scenarios) {
    let state = { index: 0, status: 'paused' };
    for (let i = 0; i < scenario.steps.length; i++) state = advance(state, scenario.steps.length);
    assert.deepEqual(state, { index: scenario.steps.length, status: 'complete' });
    assert.deepEqual(advance(state, scenario.steps.length), state);
  }
  assert.equal(new Set(allEdges().map(s => `${s.from}-${s.to}`)).size, allEdges().length);
});
