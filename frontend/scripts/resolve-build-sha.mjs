/** Choose only valid source commit IDs. Explicit Vite config wins over Pages. */
export function resolveBuildSha(env) {
  for (const value of [env.VITE_BUILD_SHA, env.CF_PAGES_COMMIT_SHA]) {
    if (typeof value !== 'string') continue;
    const sha = value.trim();
    if (/^[a-f0-9]{7,40}$/i.test(sha)) return sha;
  }
  return '';
}
