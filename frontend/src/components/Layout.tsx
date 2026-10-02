import { Bell, LogOut, Menu, MessageSquareText, Monitor, Moon, Sun, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { ApiError, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { type ThemeChoice, useTheme } from "../lib/theme";
import { useToast } from "../lib/toast";
import { MAP_ATTRIBUTION } from "./IndiaMap";
import { Button, cx, Dialog, Field, inputClass } from "./ui";

const NAV = [
  { to: "/tenders", label: "Explore" },
  { to: "/map", label: "Map" },
  { to: "/sectors", label: "Sectors" },
  { to: "/alerts", label: "Alerts" },
  { to: "/private", label: "Private", soon: true },
];

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="TenderLens home">
      <span className="grid size-8 place-items-center rounded-lg bg-brand text-brand-ink">
        <svg viewBox="0 0 32 32" className="size-5" aria-hidden="true">
          <circle cx="14" cy="14" r="7" fill="none" stroke="currentColor" strokeWidth="3" />
          <path d="M19 19l6 6" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </span>
      <span className="text-[17px] font-bold tracking-tight text-ink">TenderLens</span>
    </Link>
  );
}

function ThemeToggle() {
  const { choice, setChoice } = useTheme();
  const options: { v: ThemeChoice; icon: typeof Sun; label: string }[] = [
    { v: "light", icon: Sun, label: "Light" },
    { v: "dark", icon: Moon, label: "Dark" },
    { v: "system", icon: Monitor, label: "System" },
  ];
  return (
    <div className="flex rounded-full border border-line bg-surface p-0.5" role="radiogroup" aria-label="Colour theme">
      {options.map(({ v, icon: Icon, label }) => (
        <button
          key={v}
          role="radio"
          aria-checked={choice === v}
          title={label}
          onClick={() => setChoice(v)}
          className={cx(
            "grid size-8 place-items-center rounded-full transition-colors",
            choice === v ? "bg-surface-2 text-ink" : "text-ink-3 hover:text-ink",
          )}
        >
          <Icon className="size-4" aria-label={label} />
        </button>
      ))}
    </div>
  );
}

function UserMenu() {
  const { me, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);
  if (!me?.authenticated || !me.user) {
    return (
      <Link to="/alerts" className="inline-flex h-10 items-center rounded-full bg-brand px-4 text-sm font-semibold text-brand-ink hover:brightness-110">
        Sign in
      </Link>
    );
  }
  const u = me.user;
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 rounded-full p-0.5 hover:bg-surface-2" aria-expanded={open} aria-label="Account menu">
        {u.picture ? (
          <img src={u.picture} alt="" className="size-9 rounded-full" referrerPolicy="no-referrer" />
        ) : (
          <span className="grid size-9 place-items-center rounded-full bg-brand-soft font-semibold text-brand">{u.name[0]?.toUpperCase()}</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-64 rounded-2xl border border-line bg-surface p-2 shadow-xl shadow-black/10">
          <div className="px-3 py-2">
            <p className="truncate text-sm font-semibold text-ink">{u.name}</p>
            <p className="truncate text-xs text-ink-3">{u.email}</p>
          </div>
          <Link to="/alerts" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink hover:bg-surface-2">
            <Bell className="size-4" /> My alerts
          </Link>
          <button onClick={() => (setOpen(false), signOut())} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink hover:bg-surface-2">
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function NavItems({ onNavigate, vertical }: { onNavigate?: () => void; vertical?: boolean }) {
  return (
    <>
      {NAV.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cx(
              "inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-sm font-medium transition-colors",
              vertical && "w-full rounded-xl py-3 text-base",
              isActive ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink",
            )
          }
        >
          {n.label}
          {n.soon && <span className="rounded-full bg-brand-soft px-1.5 py-px text-[10px] font-semibold tracking-wide text-brand uppercase">Soon</span>}
        </NavLink>
      ))}
    </>
  );
}

function Header() {
  const [menu, setMenu] = useState(false);
  const loc = useLocation();
  useEffect(() => setMenu(false), [loc.pathname]);
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/80 backdrop-blur-lg">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <Logo />
        <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Main">
          <NavItems />
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <div className="hidden sm:block">
            <ThemeToggle />
          </div>
          <UserMenu />
          <button className="grid size-10 place-items-center rounded-full text-ink-2 hover:bg-surface-2 md:hidden" onClick={() => setMenu((m) => !m)} aria-label="Menu" aria-expanded={menu}>
            {menu ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </div>
      {menu && (
        <nav className="border-t border-line bg-bg px-4 pt-2 pb-4 md:hidden" aria-label="Main">
          <NavItems vertical onNavigate={() => setMenu(false)} />
          <div className="mt-3 flex items-center justify-between px-2">
            <span className="text-sm text-ink-2">Theme</span>
            <ThemeToggle />
          </div>
        </nav>
      )}
    </header>
  );
}

const FEEDBACK_KINDS = [
  { v: "bug", label: "Something is broken" },
  { v: "data", label: "Wrong or missing data" },
  { v: "idea", label: "Idea or request" },
  { v: "other", label: "Other" },
];

function FeedbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { me } = useAuth();
  const toast = useToast();
  const loc = useLocation();
  const [kind, setKind] = useState("bug");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Record<string, string[]>>({});

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError({});
    try {
      await api.feedback({ kind, message, email: email || me?.user?.email || "", page: loc.pathname + loc.search, website });
      toast("success", "Thank you, your feedback was sent.");
      setMessage("");
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.fields);
        if (err.status === 429) toast("error", "Too many messages for now. Please try again later.");
      } else toast("error", "Couldn't send feedback. Check your connection.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Send feedback">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-2">Found a bug, wrong data, or want a feature? Tell us. We read every message.</p>
        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Feedback type">
          {FEEDBACK_KINDS.map((k) => (
            <button
              type="button"
              key={k.v}
              role="radio"
              aria-checked={kind === k.v}
              onClick={() => setKind(k.v)}
              className={cx(
                "rounded-xl border px-3 py-2.5 text-left text-sm transition-colors",
                kind === k.v ? "border-brand bg-brand-soft font-medium text-brand" : "border-line text-ink-2 hover:bg-surface-2",
              )}
            >
              {k.label}
            </button>
          ))}
        </div>
        <Field label="What happened?" error={error.message?.[0]}>
          <textarea
            required
            minLength={5}
            maxLength={4000}
            rows={5}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            className={cx(inputClass, "h-auto py-3")}
            placeholder={kind === "bug" ? "What did you do, what did you expect, and what happened instead?" : "Tell us more"}
          />
        </Field>
        {!me?.authenticated && (
          <Field label="Email (optional)" hint="Only if you'd like a reply." error={error.email?.[0]}>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} placeholder="you@example.com" />
          </Field>
        )}
        {/* Honeypot for bots: visually hidden, never filled by people. */}
        <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} className="hidden" aria-hidden="true" name="website" />
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Sending…" : "Send feedback"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function Footer({ onFeedback }: { onFeedback: () => void }) {
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-3 max-w-sm text-sm text-ink-2">
            Every open government tender from NIC's public e-procurement portals, searchable in one place. Crawled politely, at one request per second.
          </p>
          <p className="mt-3 text-xs text-ink-3">Always confirm details on the official portal before bidding.</p>
        </div>
        <div>
          <p className="mb-3 text-sm font-semibold text-ink">Product</p>
          <ul className="space-y-2 text-sm text-ink-2">
            <li><Link to="/tenders" className="hover:text-ink">Explore tenders</Link></li>
            <li><Link to="/map" className="hover:text-ink">Tender map</Link></li>
            <li><Link to="/alerts" className="hover:text-ink">Email alerts</Link></li>
            <li><Link to="/private" className="hover:text-ink">Private tenders <span className="text-xs text-brand">soon</span></Link></li>
          </ul>
        </div>
        <div>
          <p className="mb-3 text-sm font-semibold text-ink">Resources</p>
          <ul className="space-y-2 text-sm text-ink-2">
            <li><a href="/api/docs/" className="hover:text-ink">API documentation</a></li>
            <li><button onClick={onFeedback} className="hover:text-ink">Report a bug</button></li>
            <li><a href="https://eprocure.gov.in/eprocure/app" target="_blank" rel="noreferrer" className="hover:text-ink">CPPP official portal ↗</a></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-line">
        <p className="mx-auto max-w-7xl px-4 py-4 text-xs text-ink-3 sm:px-6">
          Tender data: NIC GePNIC public listings. {MAP_ATTRIBUTION}.
        </p>
      </div>
    </footer>
  );
}

export function Layout() {
  const [feedback, setFeedback] = useState(false);
  const loc = useLocation();
  useEffect(() => window.scrollTo(0, 0), [loc.pathname]);
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <Header />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <Footer onFeedback={() => setFeedback(true)} />
      <button
        onClick={() => setFeedback(true)}
        className="fixed right-4 bottom-4 z-30 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2.5 text-sm font-semibold text-ink shadow-lg shadow-black/10 hover:bg-surface-2"
      >
        <MessageSquareText className="size-4 text-brand" aria-hidden="true" />
        Feedback
      </button>
      <FeedbackDialog open={feedback} onClose={() => setFeedback(false)} />
    </div>
  );
}
