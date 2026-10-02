import { Bell, Building2, CheckCircle2, FileText, Search, Sparkles } from "lucide-react";
import { useState } from "react";
import { Button, Card, inputClass } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";

const PLANNED = [
  { icon: Building2, title: "Private RFQs and RFPs", body: "Requests from companies, developers and institutions, next to government tenders." },
  { icon: Search, title: "Same search, same filters", body: "Sector, state, PIN area and value filters work across both." },
  { icon: Bell, title: "One alert for both", body: "Your existing email alerts will include private tenders if you want them." },
  { icon: FileText, title: "Post your own requirement", body: "Businesses will be able to publish an RFQ and receive quotes." },
];

export default function Private() {
  const { me } = useAuth();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <div className="hero-glow">
      <div className="mx-auto max-w-5xl px-4 py-16 text-center sm:px-6 sm:py-24">
        <span className="inline-flex items-center gap-2 rounded-full bg-brand-soft px-3 py-1 text-sm font-semibold text-brand">
          <Sparkles className="size-4" /> Coming soon
        </span>
        <h1 className="mx-auto mt-5 max-w-3xl text-4xl font-extrabold tracking-tight text-ink sm:text-5xl">Private tenders, in the same place.</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-ink-2">
          TenderLens covers government tenders today. Private-sector tenders are next. Join the waitlist and we'll email you once, when it launches.
        </p>

        {done ? (
          <p className="mx-auto mt-8 inline-flex items-center gap-2 rounded-full bg-surface px-5 py-3 font-medium text-ink shadow-sm">
            <CheckCircle2 className="size-5 text-good" /> You're on the list. Thank you!
          </p>
        ) : (
          <form
            className="mx-auto mt-8 flex max-w-md flex-col gap-2 sm:flex-row"
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
              className={inputClass}
              aria-label="Email"
            />
            <Button type="submit" variant="primary" disabled={busy} className="h-11 shrink-0">
              Join the waitlist
            </Button>
          </form>
        )}

        <div className="mt-16 grid gap-3 text-left sm:grid-cols-2">
          {PLANNED.map(({ icon: Icon, title, body }) => (
            <Card key={title} className="p-5">
              <span className="grid size-10 place-items-center rounded-xl bg-surface-2 text-ink-2">
                <Icon className="size-5" />
              </span>
              <p className="mt-3 font-semibold text-ink">{title}</p>
              <p className="mt-1 text-sm text-ink-2">{body}</p>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
