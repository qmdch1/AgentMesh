import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, writeFileSync, chmodSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writeScopedText } from '../scripts/agentmesh/scoped_write.mjs';

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'agentmesh-write-'));
  const workspace = join(root, 'workspace');
  mkdirSync(workspace);
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return { root, workspace };
}

test('Korean text has an exact ending LF and byte count', t => {
  const { workspace } = fixture(t);
  const result = writeScopedText(workspace, ['label.txt'], { path: 'label.txt', lines: ['연결하기'], final_newline: true });
  assert.deepEqual(readFileSync(result.path), Buffer.from('연결하기\n'));
  assert.equal(result.bytes, 13);
});

test('no final LF and empty files are represented explicitly', t => {
  const { workspace } = fixture(t);
  const result = writeScopedText(workspace, ['a'], { path: 'a', lines: ['text'], final_newline: false });
  assert.equal(readFileSync(result.path, 'utf8'), 'text');
  writeScopedText(workspace, ['a'], { path: 'a', lines: [], final_newline: false });
  assert.equal(statSync(result.path).size, 0);
});

test('leading whitespace, blank lines and ending blank lines survive', t => {
  const { workspace } = fixture(t);
  const result = writeScopedText(workspace, ['a'], { path: 'a', lines: ['', '  value  ', ''], final_newline: true });
  assert.equal(readFileSync(result.path, 'utf8'), '\n  value  \n\n');
});

test('undeclared files remain untouched', t => {
  const { workspace } = fixture(t);
  writeFileSync(join(workspace, 'other'), 'original');
  assert.throws(() => writeScopedText(workspace, ['allowed'], { path: 'other', lines: ['bad'] }), /write_paths/);
  assert.equal(readFileSync(join(workspace, 'other'), 'utf8'), 'original');
});

test('parent traversal, absolute escapes, root and git writes are rejected', t => {
  const { root, workspace } = fixture(t);
  for (const path of ['../outside', join(root, 'outside'), '.', '.git/config']) {
    assert.throws(() => writeScopedText(workspace, ['.', '.git/config', 'allowed'], { path, lines: ['bad'] }));
  }
});

test('file and directory symlinks cannot escape the workspace', t => {
  const { root, workspace } = fixture(t);
  const outside = join(root, 'outside');
  mkdirSync(outside); writeFileSync(join(outside, 'file'), 'original');
  symlinkSync(outside, join(workspace, 'dir'));
  symlinkSync(join(outside, 'file'), join(workspace, 'file'));
  for (const path of ['dir/file', 'file']) {
    assert.throws(() => writeScopedText(workspace, ['dir', 'file'], { path, lines: ['bad'] }), /write_paths/);
  }
  assert.equal(readFileSync(join(outside, 'file'), 'utf8'), 'original');
});

test('allowed nested files are created without extra files', t => {
  const { workspace } = fixture(t);
  writeScopedText(workspace, ['sub'], { path: 'sub/a.txt', lines: ['ok'] });
  assert.equal(readFileSync(join(workspace, 'sub/a.txt'), 'utf8'), 'ok\n');
  assert.deepEqual(readdirSync(join(workspace, 'sub')), ['a.txt']);
});

test('atomic replacements retain existing permission bits', t => {
  const { workspace } = fixture(t);
  const path = join(workspace, 'script');
  writeFileSync(path, 'before'); chmodSync(path, 0o775);
  writeScopedText(workspace, ['script'], { path: 'script', lines: ['after'] });
  assert.equal(statSync(path).mode & 0o777, 0o775);
  assert.deepEqual(readdirSync(workspace), ['script']);
});
