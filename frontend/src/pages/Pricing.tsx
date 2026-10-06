import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Check, CircleDot, Minus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { SignInDialog } from "../components/SignIn";
import { Button, ButtonLink, Card, cx, Dialog, EmptyState, Field, inputClass, PageHeader, Segmented, Skeleton, Tag } from "../components/ui";
import { api, errorMessage, type Interval, LIMIT_KEYS, type Plan } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useCheckout } from "../lib/billing";
import { formatRupees } from "../lib/format";
import { byPrice, describeLimit, LIMIT_LABELS, perMonth, priceFor, yearlySaving } from "../lib/plans";
import { usePlans, useSignedIn, useSubscription, useWorkspace } from "../lib/queries";
import { useToast } from "../lib/toast";

function Price({ plan, interval }: { plan: Plan; interval: Interval }) {
  const price = priceFor(plan, interval);
  if (price === null) {
    return (
      <div>
        <p className="num text-3xl font-medium text-ink">Custom</p>
        <p className="mt-1 text-xs text-ink-3">Priced for your volume and deployment</p>
      </div>
    );
  }
  if (price === 0) {
    return (
      <div>
        <p className="num text-3xl font-medium text-ink">₹0</p>
        <p className="mt-1 text-xs text-ink-3">Free for as long as you like</p>
      </div>
    );
  }
  const saving = interval === "year" ? yearlySaving(plan) : 0;
  return (
    <div>
      <p className="flex items-baseline gap-1.5">
        <span className="num text-3xl font-medium text-ink" data-testid={`price-${plan.code}`}>
          {formatRupees(price)}
        </span>
        <span className="text-sm text-ink-3">/ {interval === "year" ? "year" : "month"}</span>
      </p>
      <p className="mt-1 text-xs text-ink-3">
        {interval === "year" ? (
          <>
            {formatRupees(perMonth(plan, "year"))} a month, billed yearly{saving > 0 && <span className="text-signal-text"> · save {saving}%</span>}
          </>
        ) : (
          "Billed monthly · cancel any time"
        )}
      </p>
    </div>
  );
}

function Limits({ plan }: { plan: Plan }) {
  return (
    <dl className="space-y-2 text-sm">
      {LIMIT_KEYS.map((k) => {
        const v = plan.limits[k];
        const text = describeLimit(v);
        const off = text === "Not included";
        const per = typeof v === "number" && v > 0 ? LIMIT_LABELS[k].per : undefined;
        return (
          <div key={k} className="flex items-center justify-between gap-3">
            <dt className={cx("flex items-center gap-2", off ? "text-ink-3" : "text-ink-2")}>
              {off ? <Minus className="size-3.5 shrink-0" aria-hidden="true" /> : <Check className="size-3.5 shrink-0 text-good" aria-hidden="true" />}
              {LIMIT_LABELS[k].label}
            </dt>
            <dd className={cx("num text-right", off ? "text-ink-3" : "text-ink")}>
              {text}
              {per && <span className="font-sans text-xs text-ink-3"> {per}</span>}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** Enterprise is sold by a conversation; the enquiry goes through the feedback inbox. */
function ContactDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { me } = useAuth();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const send = useMutation({
    mutationFn: () =>
      api.feedback({ kind: "other", message: `Enterprise plan enquiry: ${message}`, email: email || me?.user?.email || "", page: "/pricing" }),
    onSuccess: () => {
      toast("success", "Thanks. We'll reply by email.");
      setMessage("");
      onClose();
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't send your message")),
  });
  return (
    <Dialog open={open} onClose={onClose} title="Talk to us about Enterprise">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          send.mutate();
        }}
      >
        <p className="text-sm text-ink-2">Tell us about your team, how many tenders you bid on, and whether you need the API or a private deployment.</p>
        {!me?.authenticated && (
          <Field label="Work email">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} placeholder="you@company.com" />
          </Field>
        )}
        <Field label="What do you need?">
          <textarea required minLength={5} maxLength={3000} rows={5} value={message} onChange={(e) => setMessage(e.target.value)} className={cx(inputClass, "h-auto py-2.5")} />
        </Field>
        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={send.isPending}>
            {send.isPending ? "Sending…" : "Send"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

const FAQ = [
  {
    q: "Where does the tender data come from?",
    a: (
      <>
        From the official public procurement portals listed on the{" "}
        <Link to="/coverage" className="text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
          Coverage
        </Link>{" "}
        page. We keep each tender's details with a link back to the portal that published it and never republish its documents. Always confirm on the portal before you bid.
      </>
    ),
  },
  {
    q: "Why do I upload the tender documents myself?",
    a: "Portals keep tender documents behind a CAPTCHA, and we never bypass one. Download the PDFs from the portal and upload them to the Copilot; they stay private to your workspace.",
  },
  {
    q: "What counts toward the monthly limits?",
    a: "Every question you ask the Copilot and every document you upload counts once. The counters reset on the 1st of each month.",
  },
  {
    q: "Can I cancel?",
    a: "Yes, any time, from Workspace → Billing. The workspace then moves back to the Free plan.",
  },
  {
    q: "How do I pay?",
    a: "Paid plans are billed through Razorpay. Your card or UPI details go to Razorpay, never to us.",
  },
];

export default function Pricing() {
  const plans = usePlans();
  const signedIn = useSignedIn();
  const sub = useSubscription();
  const ws = useWorkspace();
  const { checkout, awaiting } = useCheckout();
  const [interval, setPeriod] = useState<Interval>("month");
  const [signInFor, setSignInFor] = useState<Plan | null>(null);
  const [contact, setContact] = useState(false);
  const current = signedIn ? (sub.data?.plan ?? ws.data?.plan.code) : undefined;
  const list = byPrice(plans.data ?? []);
  const maxSaving = Math.max(0, ...list.map(yearlySaving));

  const choose = (plan: Plan) => {
    if (!signedIn) return setSignInFor(plan);
    checkout.mutate({ plan, interval });
  };

  const cta = (plan: Plan) => {
    const price = priceFor(plan, interval);
    if (plan.code === current) {
      return (
        <Button className="w-full" disabled>
          Current plan
        </Button>
      );
    }
    if (price === null) {
      return (
        <Button className="w-full" onClick={() => setContact(true)}>
          Talk to us
        </Button>
      );
    }
    if (price === 0) {
      return signedIn ? (
        <ButtonLink to="/workspace#billing" className="w-full" variant="ghost">
          Switch by cancelling your plan
        </ButtonLink>
      ) : (
        <Button className="w-full" onClick={() => setSignInFor(plan)}>
          Start free
        </Button>
      );
    }
    const busy = checkout.isPending && checkout.variables?.plan.code === plan.code;
    return (
      <Button variant="primary" className="w-full" onClick={() => choose(plan)} disabled={checkout.isPending || awaiting !== null}>
        {busy ? "Opening checkout…" : awaiting === plan.code ? "Activating…" : `Choose ${plan.name}`}
        {!busy && awaiting !== plan.code && <ArrowRight className="size-4" aria-hidden="true" />}
      </Button>
    );
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader
        kicker="Pricing"
        title="Start free. Pay when the bids pay."
        actions={
          <Segmented<Interval>
            label="Billing interval"
            value={interval}
            onChange={setPeriod}
            options={[
              { value: "month", label: "Monthly" },
              { value: "year", label: maxSaving > 0 ? `Yearly · save ${maxSaving}%` : "Yearly" },
            ]}
          />
        }
      >
        Search and alerts are free. Paid plans add more Copilot questions and documents, eligibility checks, CSV export and seats for your team.
      </PageHeader>

      {plans.isError ? (
        <div className="mt-8">
          <EmptyState icon={<CircleDot className="size-5" />} title="Couldn't load the plans">
            {errorMessage(plans.error)}
          </EmptyState>
        </div>
      ) : (
        <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {plans.isLoading
            ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[520px] w-full rounded-lg" />)
            : list.map((plan) => {
                const isCurrent = plan.code === current;
                return (
                  <Card key={plan.code} ticks={isCurrent} className={cx("flex flex-col p-5", isCurrent && "border-signal/60")}>
                    <div className="flex items-center justify-between gap-2">
                      <h2 className="text-lg font-semibold text-ink">{plan.name}</h2>
                      {isCurrent && (
                        <Tag tone="signal">
                          <span className="size-1.5 rounded-full bg-signal" aria-hidden="true" /> Current plan
                        </Tag>
                      )}
                    </div>
                    <div className="mt-4 min-h-[68px]">
                      <Price plan={plan} interval={interval} />
                    </div>
                    <div className="mt-5">{cta(plan)}</div>
                    <div className="mt-6 border-t border-line pt-5">
                      <Limits plan={plan} />
                    </div>
                    {plan.features.length > 0 && (
                      <ul className="mt-5 space-y-2 border-t border-line pt-5 text-sm text-ink-2">
                        {plan.features.map((f) => (
                          <li key={f} className="flex gap-2">
                            <span className="mt-[7px] size-1 shrink-0 rounded-full bg-ink-3" aria-hidden="true" />
                            {f}
                          </li>
                        ))}
                      </ul>
                    )}
                  </Card>
                );
              })}
        </div>
      )}

      {sub.data && sub.data.plan !== "free" && sub.data.current_period_end && (
        <p className="num mt-4 text-xs text-ink-3">
          Your {sub.data.interval === "year" ? "yearly" : "monthly"} subscription is {sub.data.status}. Manage it in{" "}
          <Link to="/workspace#billing" className="text-ink underline decoration-line-strong underline-offset-4">
            Workspace
          </Link>
          .
        </p>
      )}

      <section className="mt-16 grid gap-10 border-t border-line pt-10 lg:grid-cols-[1fr_2fr]">
        <div>
          <p className="label mb-3">Questions</p>
          <h2 className="text-2xl font-semibold text-ink">Before you choose</h2>
        </div>
        <dl className="divide-y divide-line border-y border-line">
          {FAQ.map((f) => (
            <div key={f.q} className="py-5">
              <dt className="font-medium text-ink">{f.q}</dt>
              <dd className="mt-1.5 text-sm text-ink-2">{f.a}</dd>
            </div>
          ))}
        </dl>
      </section>

      <SignInDialog
        open={signInFor !== null}
        onClose={() => setSignInFor(null)}
        title={signInFor && Number(signInFor.price_inr_month) > 0 ? `Sign in to choose ${signInFor.name}` : "Sign in to start free"}
        onDone={() => {
          const plan = signInFor;
          setSignInFor(null);
          if (plan && Number(plan.price_inr_month) > 0) checkout.mutate({ plan, interval });
        }}
      >
        Sign in with Google. Your workspace is created on the Free plan; nothing is charged until you confirm a payment.
      </SignInDialog>
      <ContactDialog open={contact} onClose={() => setContact(false)} />
    </div>
  );
}
