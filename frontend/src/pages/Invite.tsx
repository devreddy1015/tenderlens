import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, MailCheck, TriangleAlert } from "lucide-react";
import { useNavigate, useParams } from "react-router";
import { SignInCard } from "../components/SignIn";
import { UpgradeNotice } from "../components/Upgrade";
import { Button, ButtonLink, Card, Skeleton } from "../components/ui";
import { api, ApiError, errorMessage, quotaExceeded } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";

/** Data that belongs to the workspace you're in: after joining another one, it is all stale. */
const WORKSPACE_KEYS = ["workspace", "members", "api-keys", "pipeline", "pipeline-summary", "subscription", "copilot", "alerts"];

function failure(e: unknown): string {
  if (e instanceof ApiError && (e.status === 404 || e.status === 410)) return "This invite link is invalid, already used or expired. Ask for a new one.";
  return errorMessage(e, "Couldn't accept the invite.");
}

export default function Invite() {
  const { token = "" } = useParams();
  const { me, loading } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const accept = useMutation({
    mutationFn: () => api.workspace.acceptInvite(token),
    onSuccess: (ws) => {
      qc.removeQueries({ predicate: (q) => WORKSPACE_KEYS.includes(String(q.queryKey[0])) });
      toast("success", ws?.name ? `You've joined ${ws.name}` : "You've joined the workspace");
      nav("/workspace");
    },
  });
  const quota = quotaExceeded(accept.error);

  return (
    <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
      {loading ? (
        <Skeleton className="h-64 w-full rounded-lg" />
      ) : !me?.authenticated ? (
        <SignInCard title="Sign in to join your team's workspace">
          Use the Google account the invite was sent to. You'll share the team's bid pipeline, tender documents and plan.
        </SignInCard>
      ) : (
        <Card ticks className="p-6 sm:p-8">
          <p className="label flex items-center gap-2">
            <MailCheck className="size-3.5 text-signal-text" aria-hidden="true" /> Invitation
          </p>
          <h1 className="mt-3 text-2xl font-semibold text-ink">Join your team on TenderLens</h1>
          <p className="mt-2 text-sm text-ink-2">
            You're signed in as <span className="num text-ink">{me.user?.email}</span>. Accepting moves you into the team's workspace: you'll share its pipeline,
            documents, company profile and plan.
          </p>
          {accept.isError &&
            (quota ? (
              <UpgradeNotice className="mt-5" limit={quota.limit} message="The workspace has no free seats. Ask its owner to upgrade or remove someone." />
            ) : (
              <p className="mt-5 flex items-start gap-2 rounded-md border border-critical/40 bg-critical-soft px-3 py-2.5 text-sm text-ink" role="alert">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden="true" />
                {failure(accept.error)}
              </p>
            ))}
          <div className="mt-6 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => accept.mutate()} disabled={accept.isPending || !token}>
              {accept.isPending ? "Joining…" : "Accept invite"} <ArrowRight className="size-4" aria-hidden="true" />
            </Button>
            <ButtonLink to="/" variant="ghost">
              Not now
            </ButtonLink>
          </div>
        </Card>
      )}
    </div>
  );
}
