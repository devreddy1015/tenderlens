import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Building2, Check, Code2, Globe, KanbanSquare, LogOut, Menu, MessageSquareText, Monitor, Moon, Search, Sun, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { ApiError, api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatCount, timeAgo } from "../lib/format";
import { resetWorkspaceData, useWorkspaces } from "../lib/queries";
import { type ThemeChoice, useTheme } from "../lib/theme";
import { useToast } from "../lib/toast";
import { MAP_ATTRIBUTION } from "./IndiaMap";
import { Logo } from "./Logo";
import { UpgradeDialogHost } from "./Upgrade";
import { Button, ButtonLink, cx, Dialog, Field, inputClass, Segmented } from "./ui";

const NAV = [
  { to: "/tenders", label: "Explore" },
  { to: "/map", label: "Map" },
  { to: "/sectors", label: "Sectors" },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/copilot", label: "Copilot" },
  { to: "/alerts", label: "Alerts" },
  { to: "/pricing", label: "Pricing" },
];

/** Signed-in account menu: organisation-level pages that don't earn a top-level slot. */
const ACCOUNT_LINKS = [
  { to: "/workspace", label: "Workspace", icon: Building2 },
  { to: "/pipeline", label: "Bid pipeline", icon: KanbanSquare },
  { to: "/alerts", label: "My alerts", icon: Bell },
  { to: "/coverage", label: "Coverage", icon: Globe },
  { to: "/developers", label: "API & developers", icon: Code2 },
];

const ROLE_WORD = { owner: "Owner", admin: "Admin", member: "Member" } as const;

/** The organisations you belong to; picking one makes it active on every device (the
 *  choice is stored server-side), so all workspace data is dropped and refetched. */
function WorkspaceSwitcher({ onDone }: { onDone: () => void }) {
  const list = useWorkspaces();
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const loc = useLocation();
  const sw = useMutation({
    mutationFn: (id: number) => api.workspace.switchTo(id),
    onSuccess: (ws) => {
      resetWorkspaceData(qc, ws);
      toast("success", `Switched to ${ws.name}`);
      onDone();
      // A tender or invite page stays; workspace-only pages simply refetch.
      if (loc.pathname.startsWith("/invite/")) nav("/workspace");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't switch workspace")),
  });
  if (!list.data?.length) return null;
  return (
    <div className="border-b border-line py-1" role="group" aria-label="Workspaces">
      <p className="label px-3 pt-1.5 pb-1">Workspace</p>
      {list.data.map((w) => (
        <button
          key={w.id}
          type="button"
          aria-current={w.active ? "true" : undefined}
          disabled={w.active || sw.isPending}
          onClick={() => sw.mutate(w.id)}
          className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm text-ink-2 enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:cursor-default"
        >
          <span className="grid size-4 shrink-0 place-items-center">{w.active && <Check className="size-4 text-signal-text" aria-hidden="true" />}</span>
          <span className={cx("min-w-0 flex-1 truncate", w.active && "font-medium text-ink")}>{w.name}</span>
          <span className="num shrink-0 text-[11px] text-ink-3">{ROLE_WORD[w.role] ?? w.role}</span>
        </button>
      ))}
    </div>
  );
}

export { Logo };

function ThemeToggle() {
  const { choice, setChoice } = useTheme();
  const opts: { v: ThemeChoice; icon: typeof Sun; label: string }[] = [
    { v: "light", icon: Sun, label: "Light" },
    { v: "dark", icon: Moon, label: "Dark" },
    { v: "system", icon: Monitor, label: "System" },
  ];
  return (
    <Segmented
      label="Colour theme"
      className="seg-sm"
      value={choice}
      onChange={setChoice}
      options={opts.map(({ v, icon: Icon, label }) => ({ value: v, title: label, label: <Icon className="size-3.5" aria-label={label} /> }))}
    />
  );
}

/** Header search. Press "/" anywhere to jump into it; Enter opens the results. */
function QuickSearch({ className }: { className?: string }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      e.preventDefault();
      ref.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return (
    <form
      role="search"
      className={cx(
        "group h-8 w-64 items-center gap-2 rounded-md border border-line bg-surface px-2.5 transition-colors focus-within:border-signal hover:border-line-strong",
        className,
      )}
      onSubmit={(e) => {
        e.preventDefault();
        nav(`/tenders${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
        setQ("");
        ref.current?.blur();
      }}
    >
      <Search className="size-3.5 shrink-0 text-ink-3" aria-hidden="true" />
      <input
        ref={ref}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search tenders"
        aria-label="Search tenders"
        className="h-full min-w-0 flex-1 bg-transparent text-[13px] text-ink placeholder:text-ink-3 focus:outline-none"
      />
      <kbd className="kbd group-focus-within:hidden">/</kbd>
    </form>
  );
}

function UserMenu() {
  const { me, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("click", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", esc);
    };
  }, []);
  if (!me?.authenticated || !me.user) {
    return (
      <ButtonLink variant="primary" size="sm" to="/alerts">
        Sign in
      </ButtonLink>
    );
  }
  const u = me.user;
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="grid size-8 place-items-center overflow-hidden rounded-md border border-line bg-surface hover:border-line-strong"
        aria-expanded={open}
        aria-label="Account menu"
      >
        {u.picture ? (
          <img src={u.picture} alt="" className="size-full object-cover" referrerPolicy="no-referrer" />
        ) : (
          <span className="num text-sm font-medium text-ink">{u.name[0]?.toUpperCase()}</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-64 rounded-lg border border-line bg-surface p-1 shadow-panel">
          <div className="border-b border-line px-3 py-2.5">
            <p className="truncate text-sm font-medium text-ink">{u.name}</p>
            <p className="num truncate text-xs text-ink-3">{u.email}</p>
          </div>
          <WorkspaceSwitcher onDone={() => setOpen(false)} />
          <div className="pt-1">
            {ACCOUNT_LINKS.map(({ to, label, icon: Icon }) => (
              <Link key={to} to={to} onClick={() => setOpen(false)} className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink">
                <Icon className="size-4" aria-hidden="true" /> {label}
              </Link>
            ))}
            <button
              onClick={() => (setOpen(false), signOut())}
              className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
            >
              <LogOut className="size-4" /> Sign out
            </button>
          </div>
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
              "relative inline-flex items-center gap-1.5 rounded-md text-sm transition-colors",
              vertical ? "w-full px-3 py-3 text-base" : "h-8 px-2.5",
              isActive ? "text-ink" : "text-ink-3 hover:text-ink",
              // The active page gets an amber rule sitting on the header's bottom border.
              isActive && !vertical && "after:absolute after:inset-x-2.5 after:-bottom-[13px] after:h-px after:bg-signal",
              isActive && vertical && "bg-surface-2",
            )
          }
        >
          {n.label}
        </NavLink>
      ))}
    </>
  );
}

function Header() {
  const [menu, setMenu] = useState(false);
  const loc = useLocation();
  useEffect(() => setMenu(false), [loc.pathname]);
  const onExplore = loc.pathname === "/tenders";
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Logo />
        <nav className="hidden items-center gap-0.5 md:flex" aria-label="Main">
          <NavItems />
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {!onExplore && <QuickSearch className="hidden lg:flex" />}
          <div className="hidden sm:block">
            <ThemeToggle />
          </div>
          <UserMenu />
          <button
            className="grid size-8 place-items-center rounded-md border border-line text-ink-2 hover:bg-surface-2 md:hidden"
            onClick={() => setMenu((m) => !m)}
            aria-label="Menu"
            aria-expanded={menu}
          >
            {menu ? <X className="size-4" /> : <Menu className="size-4" />}
          </button>
        </div>
      </div>
      {menu && (
        <nav className="border-t border-line bg-bg px-4 pt-2 pb-4 md:hidden" aria-label="Main">
          <NavItems vertical onNavigate={() => setMenu(false)} />
          <div className="mt-3 flex items-center justify-between border-t border-line px-3 pt-4">
            <span className="label">Theme</span>
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
      <form onSubmit={submit} className="space-y-5">
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
                "flex items-center gap-2.5 rounded-md border px-3 py-2.5 text-left text-sm transition-colors",
                kind === k.v ? "border-signal bg-signal-soft text-ink" : "border-line text-ink-2 hover:border-line-strong hover:text-ink",
              )}
            >
              <span className={cx("size-3.5 shrink-0 rounded-full border", kind === k.v ? "border-[4px] border-signal" : "border-line-strong")} aria-hidden="true" />
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
            className={cx(inputClass, "h-auto py-2.5")}
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
        <div className="flex justify-end gap-2 border-t border-line pt-4">
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

function FooterLinks({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="label mb-4">{title}</p>
      <ul className="space-y-2.5 text-sm text-ink-2 [&_a:hover]:text-ink [&_button:hover]:text-ink">{children}</ul>
    </div>
  );
}

function Footer({ onFeedback }: { onFeedback: () => void }) {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  return (
    <footer className="mt-28 border-t border-line">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.6fr_1fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-4 max-w-sm text-sm text-ink-2">
            An index of every open tender on India's public e-procurement portals, crawled politely at one request per second.
          </p>
          <p className="num mt-5 inline-flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-xs text-ink-2">
            <span className="live-dot" aria-hidden="true" />
            {stats.data ? (
              <>
                {formatCount(stats.data.open_tenders)} open · indexed {timeAgo(stats.data.last_crawl?.finished)}
              </>
            ) : (
              "Index status…"
            )}
          </p>
        </div>
        <FooterLinks title="Product">
          <li><Link to="/tenders">Explore tenders</Link></li>
          <li><Link to="/map">Tender map</Link></li>
          <li><Link to="/sectors">Sectors</Link></li>
          <li><Link to="/pipeline">Bid pipeline</Link></li>
          <li><Link to="/copilot">Document copilot</Link></li>
          <li><Link to="/alerts">Email alerts</Link></li>
          <li><Link to="/pricing">Pricing</Link></li>
        </FooterLinks>
        <FooterLinks title="Sources">
          <li><Link to="/coverage">Coverage &amp; sources</Link></li>
          <li><a href="https://eprocure.gov.in/eprocure/app" target="_blank" rel="noreferrer">CPPP portal ↗</a></li>
          <li><Link to="/developers">API &amp; OCDS for developers</Link></li>
          <li><a href="/api/docs/">API reference</a></li>
        </FooterLinks>
        <FooterLinks title="Support">
          <li><button onClick={onFeedback}>Report a bug</button></li>
          <li><button onClick={onFeedback}>Suggest a feature</button></li>
        </FooterLinks>
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-wrap justify-between gap-x-6 gap-y-2 px-4 pt-4 pb-16 text-xs text-ink-3 sm:px-6 md:pr-36 md:pb-4">
          <p>Tender data: public listings on CPPP and NIC GePNIC portals; every tender links to its source. {MAP_ATTRIBUTION}.</p>
          <p>Always confirm details on the official portal before bidding.</p>
        </div>
      </div>
    </footer>
  );
}

export function Layout() {
  const [feedback, setFeedback] = useState(false);
  const loc = useLocation();
  // Braces matter: newer browsers return a Promise from scrollTo, and an effect may only
  // return a cleanup function.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [loc.pathname]);
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <Header />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <Footer onFeedback={() => setFeedback(true)} />
      <button onClick={() => setFeedback(true)} className="btn btn-secondary btn-sm fixed right-4 bottom-4 z-30 shadow-panel">
        <MessageSquareText className="size-3.5 text-signal-text" aria-hidden="true" />
        Feedback
      </button>
      <FeedbackDialog open={feedback} onClose={() => setFeedback(false)} />
      <UpgradeDialogHost />
    </div>
  );
}
