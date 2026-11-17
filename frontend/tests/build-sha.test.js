import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveBuildSha } from '../scripts/resolve-build-sha.mjs';

const GITHUB_SHA = '0123456789abcdef0123456789abcdef01234567';
const PAGES_SHA = '89abcdef0123456789abcdef0123456789abcdef';

test('GitHub Actions VITE_BUILD_SHA remains authoritative', () => {
  assert.equal(resolveBuildSha({ VITE_BUILD_SHA: GITHUB_SHA, CF_PAGES_COMMIT_SHA: PAGES_SHA }), GITHUB_SHA);
});

test('Cloudflare Pages commit SHA is used when VITE_BUILD_SHA is absent', () => {
  assert.equal(resolveBuildSha({ CF_PAGES_COMMIT_SHA: PAGES_SHA }), PAGES_SHA);
  assert.equal(resolveBuildSha({ VITE_BUILD_SHA: '', CF_PAGES_COMMIT_SHA: PAGES_SHA }), PAGES_SHA);
});

test('invalid or missing SHA is never presented as a build version', () => {
  assert.equal(resolveBuildSha({}), '');
  assert.equal(resolveBuildSha({ VITE_BUILD_SHA: 'not-a-sha', CF_PAGES_COMMIT_SHA: 'branch/main' }), '');
  assert.equal(resolveBuildSha({ VITE_BUILD_SHA: 'xyz1234', CF_PAGES_COMMIT_SHA: PAGES_SHA }), PAGES_SHA);
  assert.equal(resolveBuildSha({ CF_PAGES_COMMIT_SHA: 'a'.repeat(41) }), '');
  assert.equal(resolveBuildSha({ CF_PAGES_COMMIT_SHA: 1234567 }), '');
});

test('valid abbreviated SHAs and accidental surrounding whitespace are normalized', () => {
  assert.equal(resolveBuildSha({ VITE_BUILD_SHA: '  a1b2c3d  ' }), 'a1b2c3d');
});
