import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, MailCheck, TriangleAlert } from "lucide-react";
import { useNavigate, useParams } from "react-router";
import { SignInCard } from "../components/SignIn";
import { UpgradeNotice } from "../components/Upgrade";
import { Button, ButtonLink, Card, EmptyState, Skeleton } from "../components/ui";
import { api, ApiError, errorMessage, quotaExceeded, type Role } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/format";
import { resetWorkspaceData } from "../lib/queries";
import { useToast } from "../lib/toast";

const ROLE_WORD: Record<Role, string> = { owner: "an owner", admin: "an admin", member: "a member" };

function failure(e: unknown): string {
  if (e instanceof ApiError && (e.status === 404 || e.status === 410)) return "This invite link is invalid, already used or expired. Ask for a new one.";
  return errorMessage(e, "Couldn't accept the invite.");
}

/** /invite/<token>: who invited you to what (public GET), then sign in and accept. */
export default function Invite() {
  const { token = "" } = useParams();
  const { me, loading } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const preview = useQuery({ queryKey: ["invite-preview", token], queryFn: () => api.workspace.invitePreview(token), enabled: !!token, retry: false });
  const accept = useMutation({
    mutationFn: () => api.workspace.acceptInvite(token),
    meta: { inlineQuota: true },
    onSuccess: (ws) => {
      // The joined workspace is now the active one: everything workspace-scoped is stale.
      resetWorkspaceData(qc, ws);
      toast("success", ws?.name ? `You've joined ${ws.name}` : "You've joined the workspace");
      nav("/workspace");
    },
  });
  const quota = quotaExceeded(accept.error);
  const inv = preview.data;
  const signedInAs = me?.user?.email ?? "";
  const wrongEmail = !!inv && !!signedInAs && inv.email.toLowerCase() !== signedInAs.toLowerCase();

  if (loading || preview.isLoading) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
    );
  }
  if (preview.isError || !inv) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
        <EmptyState icon={<TriangleAlert className="size-5" />} title="This invite can't be used">
          {failure(preview.error)}
          <div className="mt-4">
            <ButtonLink to="/" size="sm">
              Go to TenderLens
            </ButtonLink>
          </div>
        </EmptyState>
      </div>
    );
  }

  const summary = (
    <>
      <span className="font-medium text-ink">{inv.organization}</span> invited <span className="num text-ink">{inv.email}</span> to join as{" "}
      {ROLE_WORD[inv.role] ?? inv.role}. The link expires {formatDate(inv.expires_at, false)}.
    </>
  );

  return (
    <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
      {!me?.authenticated ? (
        <SignInCard title={`Sign in to join ${inv.organization}`}>
          {summary} Use the Google account for that address. You'll share the team's bid pipeline, tender documents and plan.
        </SignInCard>
      ) : (
        <Card ticks className="p-6 sm:p-8">
          <p className="label flex items-center gap-2">
            <MailCheck className="size-3.5 text-signal-text" aria-hidden="true" /> Invitation
          </p>
          <h1 className="mt-3 text-2xl font-semibold text-ink">Join {inv.organization} on TenderLens</h1>
          <p className="mt-2 text-sm text-ink-2">{summary}</p>
          <p className="mt-2 text-sm text-ink-2">
            Accepting makes it your active workspace: you'll share its pipeline, documents, company profile and plan. Your own workspace stays in the account menu.
          </p>
          {wrongEmail && (
            <p className="mt-5 flex items-start gap-2 rounded-md border border-critical/40 bg-critical-soft px-3 py-2.5 text-sm text-ink" role="alert">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden="true" />
              You're signed in as {signedInAs}. Sign out and sign in as {inv.email} to accept.
            </p>
          )}
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
            <Button variant="primary" onClick={() => accept.mutate()} disabled={accept.isPending || wrongEmail}>
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
