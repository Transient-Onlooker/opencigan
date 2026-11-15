import type { School } from './api';

/** A shared link may select only a fresh search result with matching identity. */
export function verifiedSharedSchool(shared: School, results: School[], stale: boolean): School | undefined {
  if (stale) return undefined;
  return results.find((candidate) => candidate.id === shared.id && candidate.name === shared.name && candidate.region === shared.region);
}
