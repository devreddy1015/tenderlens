import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BidStatus, type BidTrack, type BidTrackPatch, errorMessage, type Source } from "./api";
import { useAuth } from "./auth";
import { useToast } from "./toast";

/** Shared queries for signed-in data. Keys listed in PRIVATE_KEYS (auth.tsx) are dropped on sign-out. */

export function useSignedIn(): boolean {
  return !!useAuth().me?.authenticated;
}

export function useWorkspace() {
  const signedIn = useSignedIn();
  return useQuery({ queryKey: ["workspace"], queryFn: api.workspace.get, enabled: signedIn, staleTime: 30_000 });
}

export function useSubscription() {
  const signedIn = useSignedIn();
  return useQuery({ queryKey: ["subscription"], queryFn: api.billing.subscription, enabled: signedIn });
}

export function usePipeline() {
  const signedIn = useSignedIn();
  return useQuery({ queryKey: ["pipeline"], queryFn: () => api.pipeline.list(), enabled: signedIn });
}

export function usePipelineSummary() {
  const signedIn = useSignedIn();
  return useQuery({ queryKey: ["pipeline-summary"], queryFn: api.pipeline.summary, enabled: signedIn });
}

export function useMembers(enabled = true) {
  const signedIn = useSignedIn();
  return useQuery({ queryKey: ["members"], queryFn: api.workspace.members, enabled: signedIn && enabled, staleTime: 60_000 });
}

/** The portals we index (public). Shared by the tender page, Coverage, Home and the footer. */
export function useSources() {
  return useQuery({ queryKey: ["sources"], queryFn: api.sources, staleTime: 5 * 60_000, retry: false });
}

/** One source by key, for attribution: its name and the portal to link out to. */
export function useSource(key: string | undefined): Source | undefined {
  const sources = useSources();
  return key ? sources.data?.find((s) => s.key === key) : undefined;
}

export const CPPP_URL = "https://eprocure.gov.in/eprocure/app";

/** Where to send a bidder for a tender's documents: the home of the portal that published it.
 *  GePNIC detail links expire with the portal session, so we never deep-link those. */
export function usePortalUrl(sourceKey: string | undefined): string {
  return useSource(sourceKey)?.url || CPPP_URL;
}

export function usePlans() {
  return useQuery({ queryKey: ["plans"], queryFn: api.billing.plans, staleTime: 10 * 60_000 });
}

const byTender = (rows: BidTrack[]) => new Map(rows.map((r) => [r.tender.id, r]));

/** The pipeline entry for a tender, if the workspace tracks it. One request serves every
 *  card on the page: they share the ["pipeline"] query. */
export function useTracked(tenderId: number): BidTrack | undefined {
  const signedIn = useSignedIn();
  const q = useQuery({ queryKey: ["pipeline"], queryFn: () => api.pipeline.list(), enabled: signedIn, select: byTender });
  return q.data?.get(tenderId);
}

export function useTrack() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ tender, status }: { tender: number; status?: BidStatus }) => api.pipeline.track(tender, status),
    onSuccess: (track) => {
      qc.setQueryData<BidTrack[]>(["pipeline"], (rows) => rows && [...rows.filter((r) => r.id !== track.id), track]);
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["pipeline-summary"] });
      toast("success", "Added to your bid pipeline");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't add it to the pipeline")),
  });
}

/** PATCH a bid, showing the change at once and rolling back if the server refuses it. */
export function useUpdateTrack() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: BidTrackPatch }) => api.pipeline.update(id, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: ["pipeline"] });
      const prev = qc.getQueryData<BidTrack[]>(["pipeline"]);
      qc.setQueryData<BidTrack[]>(["pipeline"], (rows) =>
        rows?.map((r) =>
          r.id === id
            ? {
                ...r,
                status: patch.status ?? r.status,
                notes: patch.notes ?? r.notes,
                bid_amount_inr: patch.bid_amount_inr !== undefined ? patch.bid_amount_inr : r.bid_amount_inr,
              }
            : r,
        ),
      );
      return { prev };
    },
    onError: (e, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["pipeline"], ctx.prev);
      toast("error", errorMessage(e, "Couldn't update the bid"));
    },
    onSuccess: (track) => {
      if (track) qc.setQueryData<BidTrack[]>(["pipeline"], (rows) => rows?.map((r) => (r.id === track.id ? track : r)));
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["pipeline-summary"] }),
  });
}

export function useRemoveTrack() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (id: number) => api.pipeline.remove(id),
    onSuccess: (_r, id) => {
      qc.setQueryData<BidTrack[]>(["pipeline"], (rows) => rows?.filter((r) => r.id !== id));
      qc.invalidateQueries({ queryKey: ["pipeline-summary"] });
      toast("success", "Removed from the pipeline");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't remove it")),
  });
}
