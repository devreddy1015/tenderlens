import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { reportQuota } from "./upgrade";

declare module "@tanstack/react-query" {
  interface Register {
    /** `inlineQuota`: the component shows its own UpgradeNotice, so the global prompt stays shut. */
    queryMeta: { inlineQuota?: boolean };
    mutationMeta: { inlineQuota?: boolean };
  }
}

/** The app's query client. Any 402 quota_exceeded that no component handles inline opens
 *  the one upgrade dialog (components/Upgrade.tsx). Tests build theirs here too, with
 *  `retry: false`. */
export function createQueryClient(opts: { retry?: boolean } = {}) {
  return new QueryClient({
    queryCache: new QueryCache({ onError: (e, q) => q.meta?.inlineQuota || reportQuota(e) }),
    mutationCache: new MutationCache({ onError: (e, _v, _c, m) => m.meta?.inlineQuota || reportQuota(e) }),
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        // A 4xx (signed out, over quota, not found) won't change on a retry; a network blip may.
        retry: opts.retry === false ? false : (failures, e) => failures < 1 && !(e instanceof ApiError && e.status >= 400 && e.status < 500),
      },
      mutations: opts.retry === false ? { retry: false } : undefined,
    },
  });
}
