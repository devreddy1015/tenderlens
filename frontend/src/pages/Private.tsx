import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bell, Building2, Check, FileText, Search } from "lucide-react";
import { useState } from "react";
import { InterfaceLines } from "../components/InterfaceLines";
import { Button, Card, cx, inputClass, Tag } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatCount } from "../lib/format";
import { useToast } from "../lib/toast";

const PLANNED = [
  { icon: Building2, title: "Private RFQs and RFPs", body: "Requests from companies, developers and institutions, listed next to government tenders." },
  { icon: Search, title: "Same search, same filters", body: "Sector, state, PIN area and value filters work across both, in one result list." },
  { icon: Bell, title: "One alert for both", body: "Your existing email alerts can include private tenders, if you want them to." },
  { icon: FileText, title: "Post your own requirement", body: "Businesses will be able to publish an RFQ and collect quotes from suppliers." },
];

function StatusRow({ label, status, detail }: { label: string; status: React.ReactNode; detail: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line py-3.5 last:border-0">
      <div>
        <p className="text-sm font-medium text-ink">{label}</p>
        <p className="num mt-1 text-xs text-ink-3">{detail}</p>
      </div>
      {status}
    </div>
  );
}

export default function Private() {
  const { me } = useAuth();
  const toast = useToast();
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <div>
      <section className="relative overflow-hidden border-b border-line">
        <InterfaceLines className="field-mask-hero [--calm-h:52%] [--calm-w:40%] [--calm-x:24%] [--calm-y:48%]" />
        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1.35fr_1fr]">
          <div>
            <p className="eyebrow">Coming soon · Private sector</p>
            <h1 className="mt-5 max-w-2xl text-4xl font-semibold text-ink sm:text-[3.25rem] sm:leading-[1.05]">
              Private tenders, <span className="block text-ink-3">in the same place.</span>
            </h1>
            <p className="mt-5 max-w-xl text-[17px] text-ink-2">
              TenderLens indexes government tenders today. Private-sector RFQs and RFPs are next. Join the waitlist and we'll email you once, when it launches.
            </p>

            {done ? (
              <div className="mt-8 flex max-w-md items-start gap-3 rounded-md border border-good/40 bg-good-soft px-4 py-3" role="status">
                <Check className="mt-0.5 size-4 shrink-0 text-good" aria-hidden="true" />
                <div>
                  <p className="text-sm font-medium text-ink">You're on the list.</p>
                  <p className="num mt-0.5 text-xs text-ink-2">One email to {email || me?.user?.email || "you"} at launch. Nothing else.</p>
                </div>
              </div>
            ) : (
              <form
                className="mt-8 flex max-w-md flex-col gap-2 sm:flex-row"
                onSubmit={async (e) => {
                  e.preventDefault();
                  setBusy(true);
                  try {
                    await api.feedback({ kind: "private_waitlist", email: email || me?.user?.email || "", page: "/private" });
                    setDone(true);
                  } catch (err) {
                    toast("error", err instanceof ApiError ? err.message : "Couldn't join the waitlist");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <input
                  type="email"
                  required={!me?.authenticated}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={me?.user?.email ?? "you@company.com"}
                  className={cx(inputClass, "h-11 bg-surface/90 backdrop-blur")}
                  aria-label="Email"
                />
                <Button type="submit" variant="primary" disabled={busy} className="h-11 shrink-0">
                  {busy ? "Joining…" : "Join the waitlist"} <ArrowRight className="size-4" aria-hidden="true" />
                </Button>
              </form>
            )}
            <p className="mt-3 text-xs text-ink-3">No newsletter. One email when it launches.</p>
          </div>

          <Card ticks className="bg-surface/90 p-5 backdrop-blur sm:p-6">
            <p className="label">Coverage status</p>
            <div className="mt-2">
              <StatusRow
                label="Government tenders"
                detail={stats.data ? `${formatCount(stats.data.open_tenders)} open · refreshed hourly` : "Refreshed hourly"}
                status={
                  <Tag tone="good">
                    <span className="live-dot" aria-hidden="true" /> Live
                  </Tag>
                }
              />
              <StatusRow label="Private RFQs and RFPs" detail="Companies, developers, institutions" status={<Tag tone="signal">In development</Tag>} />
              <StatusRow label="Post a requirement" detail="Publish an RFQ, collect quotes" status={<Tag>Planned</Tag>} />
            </div>
          </Card>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pt-16 sm:px-6">
        <p className="label mb-5 flex items-center gap-3">
          <span className="text-signal-text">Roadmap</span>
          <span className="h-px w-6 bg-line-strong" aria-hidden="true" />
          What's coming
        </p>
        <div className="grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2">
          {PLANNED.map(({ icon: Icon, title, body }, i) => (
            <div key={title} className="bg-surface p-6 sm:p-7">
              <div className="flex items-center justify-between">
                <span className="num text-xs text-signal-text">{String(i + 1).padStart(2, "0")}</span>
                <Icon className="size-[18px] text-ink-3" aria-hidden="true" />
              </div>
              <p className="mt-6 font-medium text-ink">{title}</p>
              <p className="mt-1.5 max-w-sm text-sm text-ink-2">{body}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
