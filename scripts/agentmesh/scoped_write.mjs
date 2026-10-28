import { chmodSync, existsSync, lstatSync, mkdirSync, realpathSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { basename, dirname, isAbsolute, relative, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';

export function scopedPath(workspace, scope, path) {
  const root = realpathSync(workspace);
  let parent = resolve(root, path);
  const missing = [];
  while (!existsSync(parent) && dirname(parent) !== parent) {
    missing.unshift(basename(parent));
    parent = dirname(parent);
  }
  const target = resolve(realpathSync(parent), ...missing);
  const rel = relative(root, target);
  if (!rel || isAbsolute(rel) || rel === '..' || rel.startsWith('../') || rel.split('/').includes('.git') ||
      !scope.some(s => s !== '.' && (rel === s.replace(/\/$/, '') || rel.startsWith(s.replace(/\/$/, '') + '/')))) {
    throw new Error('Outside task write_paths');
  }
  return target;
}

export function writeScopedText(workspace, scope, { path, lines, final_newline = true }) {
  if (!Array.isArray(lines) || !lines.every(line => typeof line === 'string') || typeof final_newline !== 'boolean') {
    throw new Error('lines must be a string array; final_newline must be boolean');
  }
  const target = scopedPath(workspace, scope, path);
  const content = lines.join('\n') + (final_newline ? '\n' : '');
  mkdirSync(dirname(target), { recursive: true });
  const temp = resolve(dirname(target), `.${basename(target)}.agentmesh-${randomUUID()}.tmp`);
  const mode = existsSync(target) ? lstatSync(target).mode & 0o777 : null;
  try {
    writeFileSync(temp, content, { mode: mode ?? 0o644, flag: 'wx' });
    if (mode !== null) chmodSync(temp, mode);
    renameSync(temp, target);
  } finally {
    if (existsSync(temp)) unlinkSync(temp);
  }
  return { path: target, bytes: Buffer.byteLength(content, 'utf8') };
}
