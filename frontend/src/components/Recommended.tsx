import { ArrowRight, ChevronLeft, ChevronRight, Sparkles, UserRoundCog } from "lucide-react";
import { Link } from "react-router";
import { errorMessage, PAGE_SIZE } from "../lib/api";
import { formatCount } from "../lib/format";
import { useRecommendations, useSignedIn } from "../lib/queries";
import { TenderCard, TenderListHeader, TenderRow, TenderRowSkeleton } from "./TenderCard";
import { Button, ButtonLink, Card, Skeleton } from "./ui";

/** Recommendations need the company profile (states, sectors, turnover): ask for it. */
export function ProfileCta({ className }: { className?: string }) {
  return (
    <Card ticks className={className}>
      <div className="flex flex-wrap items-center gap-4 p-5 sm:p-6">
        <span className="grid size-10 shrink-0 place-items-center rounded-md border border-line bg-surface-2 text-signal-text">
          <UserRoundCog className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-ink">Tell us what you bid for</p>
          <p className="mt-0.5 text-sm text-ink-2">
            Add the states you work in, your kinds of work and your turnover. We'll pick the open tenders that fit, and say why each one does.
          </p>
        </div>
        <ButtonLink to="/workspace#profile" variant="primary">
          Complete your company profile <ArrowRight className="size-4" aria-hidden="true" />
        </ButtonLink>
      </div>
    </Card>
  );
}

const NO_MATCH =
  "No open tender matches your profile right now. New tenders arrive every hour; widen your states or kinds of work to see more.";

/** Home: the first few recommendations as cards, for signed-in users only. */
export function RecommendedSection() {
  const signedIn = useSignedIn();
  const q = useRecommendations(1, signedIn);
  if (!signedIn) return null;
  const d = q.data;
  return (
    <section className="border-t border-line" aria-labelledby="recommended-heading">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-20">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-2xl">
            <p className="label mb-3 flex items-center gap-2">
              <Sparkles className="size-3.5 text-signal-text" aria-hidden="true" /> For your company
            </p>
            <h2 id="recommended-heading" className="text-2xl font-semibold text-ink sm:text-[28px] sm:leading-tight">
              Recommended for you
            </h2>
            <p className="mt-2 text-ink-2">Open tenders that match your states, kinds of work and turnover. Every plan, no extra charge.</p>
          </div>
          {d && !d.profile_incomplete && d.count > 0 && (
            <ButtonLink to="/tenders?view=recommended" size="sm">
              See all {formatCount(d.count)} <ArrowRight className="size-3.5" aria-hidden="true" />
            </ButtonLink>
          )}
        </div>
        {q.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-44 w-full rounded-lg" />
            ))}
          </div>
        ) : q.isError ? (
          <p className="text-sm text-critical">{errorMessage(q.error)}</p>
        ) : d?.profile_incomplete ? (
          <ProfileCta />
        ) : !d?.results.length ? (
          <p className="rounded-md border border-line px-4 py-4 text-sm text-ink-2">{NO_MATCH}</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.results.slice(0, 6).map((t) => (
              <TenderCard key={t.id} t={t} reasons={t.reasons} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** Explore's "Recommended for you" tab: the full, paginated list. */
export function RecommendedList({ page, onPage }: { page: number; onPage: (p: number) => void }) {
  const q = useRecommendations(page);
  const d = q.data;
  const pages = d ? Math.max(1, Math.ceil(d.count / PAGE_SIZE)) : 1;
  if (q.isError) return <p className="text-sm text-critical">{errorMessage(q.error)}</p>;
  if (d?.profile_incomplete) return <ProfileCta />;
  return (
    <div>
      <p className="mb-4 text-sm text-ink-3" aria-live="polite">
        {d ? `${formatCount(d.count)} open tenders match your company profile, newest first.` : "Matching tenders to your profile…"}{" "}
        <Link to="/workspace#profile" className="font-medium text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink">
          Edit profile
        </Link>
      </p>
      {d && d.count === 0 ? (
        <p className="rounded-md border border-line px-4 py-4 text-sm text-ink-2">{NO_MATCH}</p>
      ) : (
        <div className="panel overflow-hidden">
          <TenderListHeader />
          {q.isLoading ? Array.from({ length: 4 }, (_, i) => <TenderRowSkeleton key={i} />) : d?.results.map((t) => <TenderRow key={t.id} t={t} reasons={t.reasons} />)}
        </div>
      )}
      {pages > 1 && (
        <nav className="mt-6 flex items-center justify-between gap-3" aria-label="Pages">
          <Button size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            <ChevronLeft className="size-4" aria-hidden="true" /> Previous
          </Button>
          <p className="num text-sm text-ink-3">
            Page <span className="text-ink">{page}</span> / {pages}
          </p>
          <Button size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
            Next <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </nav>
      )}
    </div>
  );
}
