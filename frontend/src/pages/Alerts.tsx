import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Mail, MapPin, Pencil, Plus, Send, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import indiaData from "../data/india-states.json";
import { Button, Card, cx, EmptyState, Field, inputClass, Skeleton } from "../components/ui";
import { type Alert, type AlertCriteria, ApiError, api } from "../lib/api";
import { GoogleButton, useAuth } from "../lib/auth";
import { formatCount, formatDate, formatInr } from "../lib/format";
import { SECTORS, SectorIcon, sectorMeta } from "../lib/sectors";
import { useToast } from "../lib/toast";

const ALL_STATES = (indiaData as { states: { name: string }[] }).states.map((s) => s.name).sort();
const PIN_SHORTCUTS = [
  { pin: "490", label: "Bhilai / Durg" },
  { pin: "492", label: "Raipur" },
  { pin: "495", label: "Bilaspur" },
  { pin: "110", label: "New Delhi" },
  { pin: "400", label: "Mumbai" },
];
const MIN_VALUES = [
  { v: "", label: "Any value" },
  { v: "1000000", label: "₹10 lakh or more" },
  { v: "10000000", label: "₹1 crore or more" },
  { v: "100000000", label: "₹10 crore or more" },
];

type Draft = AlertCriteria & { name: string };
const EMPTY: Draft = { name: "", states: [], pin_prefixes: [], sectors: [], keywords: "", min_value_inr: null };

function suggestName(d: Draft): string {
  const where = [...d.states, ...d.pin_prefixes.map((p) => PIN_SHORTCUTS.find((s) => s.pin === p)?.label ?? `PIN ${p}`)];
  const what = d.sectors.map((s) => sectorMeta(s).label);
  return [what.slice(0, 2).join(", ") || "Tenders", where.length ? `in ${where.slice(0, 2).join(", ")}` : "across India"].join(" ");
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function StatePicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const options = ALL_STATES.filter((s) => !value.includes(s) && s.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="relative">
      <div className={cx(inputClass, "flex h-auto min-h-11 flex-wrap items-center gap-1.5 py-1.5")}>
        {value.map((s) => (
          <span key={s} className="inline-flex items-center gap-1 rounded-full bg-brand-soft py-0.5 pr-1 pl-2.5 text-sm text-brand">
            {s}
            <button type="button" onClick={() => onChange(value.filter((x) => x !== s))} aria-label={`Remove ${s}`} className="rounded-full p-0.5 hover:bg-brand/10">
              <X className="size-3.5" />
            </button>
          </span>
        ))}
        <input
          value={q}
          onChange={(e) => (setQ(e.target.value), setOpen(true))}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && options[0]) {
              e.preventDefault();
              onChange([...value, options[0]]);
              setQ("");
            }
          }}
          placeholder={value.length ? "Add another state" : "Type a state, e.g. Chhattisgarh"}
          className="h-8 min-w-40 flex-1 bg-transparent text-sm focus:outline-none"
          aria-label="Add a state"
          role="combobox"
          aria-expanded={open}
        />
      </div>
      {open && options.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-60 w-full overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-xl shadow-black/10" role="listbox">
          {options.map((s) => (
            <li key={s}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => (onChange([...value, s]), setQ(""))}
                className="w-full rounded-lg px-3 py-2 text-left text-sm text-ink hover:bg-surface-2"
              >
                {s}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AlertForm({
  initial,
  editing,
  onSaved,
  onCancel,
}: {
  initial: Draft;
  editing?: Alert;
  onSaved: () => void;
  onCancel?: () => void;
}) {
  const { me } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(initial);
  const [pin, setPin] = useState("");
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  useEffect(() => setD(initial), [initial]);

  const criteria = useDebounced<AlertCriteria>(
    { states: d.states, pin_prefixes: d.pin_prefixes, sectors: d.sectors, keywords: d.keywords, min_value_inr: d.min_value_inr },
    400,
  );
  const preview = useQuery({ queryKey: ["alert-preview", criteria], queryFn: () => api.previewAlert(criteria), placeholderData: keepPreviousData });

  const save = useMutation({
    mutationFn: () => {
      const body = { ...d, name: d.name.trim() || suggestName(d) };
      return editing ? api.updateAlert(editing.id, body) : api.createAlert(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] });
      toast("success", editing ? "Alert updated" : `Alert created. Check ${me?.user?.email} for the tenders open right now.`);
      setErrors({});
      onSaved();
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        setErrors(e.fields);
        toast("error", e.message);
      } else toast("error", "Couldn't save the alert");
    },
  });

  const addPin = (p: string) => {
    const clean = p.trim();
    if (/^[1-9]\d{1,5}$/.test(clean) && !d.pin_prefixes.includes(clean)) setD({ ...d, pin_prefixes: [...d.pin_prefixes, clean] });
    setPin("");
  };

  // Only the fields live in the <form>; the sidebar (with the sign-in form) sits outside
  // it, because forms can't nest. The save button joins the form through its id.
  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_300px]">
      <form
        id="alert-form"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        className="space-y-6"
      >
        <Field label="Where" hint="Choose states, PIN areas, or both. Leave empty for all of India." error={errors.states?.[0]}>
          <StatePicker value={d.states} onChange={(states) => setD({ ...d, states })} />
        </Field>

        <div>
          <span className="mb-1.5 block text-sm font-medium text-ink">PIN areas</span>
          <div className="flex flex-wrap items-center gap-1.5">
            {d.pin_prefixes.map((p) => (
              <span key={p} className="inline-flex items-center gap-1 rounded-full bg-brand-soft py-1 pr-1 pl-3 text-sm text-brand">
                <MapPin className="size-3.5" /> {PIN_SHORTCUTS.find((s) => s.pin === p)?.label ?? "PIN"} {p}xxx
                <button type="button" onClick={() => setD({ ...d, pin_prefixes: d.pin_prefixes.filter((x) => x !== p) })} aria-label={`Remove PIN ${p}`} className="rounded-full p-0.5 hover:bg-brand/10">
                  <X className="size-3.5" />
                </button>
              </span>
            ))}
            <span className="w-32">
              <input
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
                onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addPin(pin))}
                inputMode="numeric"
                placeholder="PIN prefix"
                className={cx(inputClass, "h-9")}
                aria-label="PIN code prefix"
              />
            </span>
            <Button type="button" size="sm" onClick={() => addPin(pin)} disabled={pin.length < 2}>
              <Plus className="size-4" /> Add
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {PIN_SHORTCUTS.filter((s) => !d.pin_prefixes.includes(s.pin)).map((s) => (
              <button type="button" key={s.pin} onClick={() => addPin(s.pin)} className="rounded-full border border-dashed border-line px-2.5 py-1 text-xs text-ink-2 hover:border-brand hover:text-brand">
                + {s.label} ({s.pin})
              </button>
            ))}
          </div>
          {errors.pin_prefixes && <p className="mt-1.5 text-xs text-critical">{errors.pin_prefixes[0]}</p>}
          <p className="mt-1.5 text-xs text-ink-3">The first 3 digits of a PIN code cover a district: 490 is Bhilai and Durg.</p>
        </div>

        <div>
          <span className="mb-1.5 block text-sm font-medium text-ink">What kind of work</span>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Sectors">
            {SECTORS.map((s) => {
              const on = d.sectors.includes(s.slug);
              return (
                <button
                  type="button"
                  key={s.slug}
                  aria-pressed={on}
                  onClick={() => setD({ ...d, sectors: on ? d.sectors.filter((x) => x !== s.slug) : [...d.sectors, s.slug] })}
                  className={cx(
                    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors",
                    on ? "border-brand bg-brand-soft font-medium text-brand" : "border-line text-ink-2 hover:bg-surface-2",
                  )}
                >
                  <SectorIcon slug={s.slug} /> {s.label}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-xs text-ink-3">None selected means every sector.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Keywords (optional)" hint="Comma-separated. Any one must appear in the title." error={errors.keywords?.[0]}>
            <input value={d.keywords} onChange={(e) => setD({ ...d, keywords: e.target.value })} placeholder="e.g. CCTV, solar" className={inputClass} />
          </Field>
          <Field label="Minimum value">
            <select value={d.min_value_inr ?? ""} onChange={(e) => setD({ ...d, min_value_inr: e.target.value || null })} className={inputClass}>
              {MIN_VALUES.map((m) => (
                <option key={m.v} value={m.v}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Alert name" hint={`Leave empty to use “${suggestName(d)}”.`} error={errors.name?.[0]}>
          <input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} maxLength={120} placeholder={suggestName(d)} className={inputClass} />
        </Field>
        {errors.non_field_errors && <p className="text-sm text-critical">{errors.non_field_errors[0]}</p>}
      </form>

      <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        <Card className="p-5">
          <p className="text-sm text-ink-2">Open tenders matching right now</p>
          <p className="mt-1 text-4xl font-bold tracking-tight text-ink tabular-nums" aria-live="polite">
            {preview.data ? formatCount(preview.data.count) : <Skeleton className="h-10 w-16" />}
          </p>
          <ul className="mt-4 space-y-3">
            {preview.data?.sample.map((t) => (
              <li key={t.id} className="text-sm">
                <Link to={`/tenders/${t.id}`} className="line-clamp-2 font-medium text-ink hover:text-brand">
                  {t.title}
                </Link>
                <p className="text-xs text-ink-3">
                  {t.state} · {formatInr(t.value_inr, { short: true })}
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-4 border-t border-line pt-3 text-xs text-ink-3">
            You'll get one email listing these now, then one after each hourly crawl when new ones open. Nothing if nothing is new.
          </p>
        </Card>
        {me?.authenticated ? (
          <div className="flex gap-2">
            {onCancel && (
              <Button type="button" variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
            )}
            <Button type="submit" form="alert-form" variant="primary" className="flex-1" disabled={save.isPending}>
              <BellRing className="size-4" /> {save.isPending ? "Saving…" : editing ? "Save changes" : "Create alert"}
            </Button>
          </div>
        ) : (
          <Card className="p-5">
            <p className="font-semibold text-ink">Sign in to save this alert</p>
            <p className="mt-1 mb-4 text-sm text-ink-2">We email alerts to your Google account address. Your choices above are kept.</p>
            <GoogleButton />
          </Card>
        )}
      </aside>
    </div>
  );
}

function AlertRow({ a, onEdit }: { a: Alert; onEdit: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const toggle = useMutation({
    mutationFn: () => api.updateAlert(a.id, { active: !a.active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const del = useMutation({
    mutationFn: () => api.deleteAlert(a.id),
    onSuccess: () => (qc.invalidateQueries({ queryKey: ["alerts"] }), toast("success", "Alert deleted")),
  });
  const test = useMutation({
    mutationFn: () => api.testAlert(a.id),
    onSuccess: (r) => toast("success", `Test email sent to ${r.sent_to} (${r.matching} open tenders match)`),
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "Couldn't send the test email"),
  });
  const where = [...a.states, ...a.pin_prefixes.map((p) => `PIN ${p}xxx`)];
  return (
    <Card className={cx("p-5", !a.active && "opacity-70")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-ink">{a.name}</p>
          <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-ink-2">
              <MapPin className="size-3.5" /> {where.length ? where.join(", ") : "All of India"}
            </span>
            {a.sectors.map((s) => (
              <span key={s} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-ink-2">
                <SectorIcon slug={s} className="size-3.5" /> {sectorMeta(s).label}
              </span>
            ))}
            {a.keywords && <span className="rounded-full bg-surface-2 px-2.5 py-1 text-ink-2">“{a.keywords}”</span>}
            {a.min_value_inr && <span className="rounded-full bg-surface-2 px-2.5 py-1 text-ink-2">≥ {formatInr(a.min_value_inr, { short: true })}</span>}
          </div>
          <p className="mt-2 text-xs text-ink-3">{a.last_sent_at ? `Last email ${formatDate(a.last_sent_at)}` : "No email sent yet"}</p>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-2">
          <span>{a.active ? "On" : "Paused"}</span>
          <button
            type="button"
            role="switch"
            aria-checked={a.active}
            aria-label={`${a.active ? "Pause" : "Resume"} ${a.name}`}
            onClick={() => toggle.mutate()}
            className={cx("relative h-6 w-11 rounded-full transition-colors", a.active ? "bg-brand" : "bg-line")}
          >
            <span className={cx("absolute top-0.5 size-5 rounded-full bg-white shadow transition-[left]", a.active ? "left-[22px]" : "left-0.5")} />
          </button>
        </label>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-3">
        <Button size="sm" variant="ghost" onClick={() => test.mutate()} disabled={test.isPending}>
          <Send className="size-4" /> {test.isPending ? "Sending…" : "Send test email"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onEdit}>
          <Pencil className="size-4" /> Edit
        </Button>
        {confirm ? (
          <span className="ml-auto inline-flex items-center gap-2 text-sm">
            Delete this alert?
            <Button size="sm" variant="danger" onClick={() => del.mutate()}>
              Delete
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
              Keep
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" className="ml-auto text-critical" onClick={() => setConfirm(true)}>
            <Trash2 className="size-4" /> Delete
          </Button>
        )}
      </div>
    </Card>
  );
}

export default function Alerts() {
  const { me, loading } = useAuth();
  const [params] = useSearchParams();
  const fromUrl = useMemo<Draft>(
    () => ({
      ...EMPTY,
      states: params.getAll("state").filter((s) => ALL_STATES.includes(s)),
      sectors: params.getAll("sector").filter((s) => SECTORS.some((x) => x.slug === s)),
      pin_prefixes: params.getAll("pin").filter((p) => /^[1-9]\d{1,5}$/.test(p)),
      keywords: params.get("keywords") ?? "",
    }),
    [params],
  );
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts, enabled: !!me?.authenticated });
  const [mode, setMode] = useState<"new" | Alert | null>(null);
  const showForm = mode !== null || !me?.authenticated || (alerts.data?.length === 0 && !alerts.isLoading) || params.size > 0;
  const editing = mode && mode !== "new" ? mode : undefined;
  const initial = useMemo<Draft>(
    () => (editing ? { name: editing.name, states: editing.states, pin_prefixes: editing.pin_prefixes, sectors: editing.sectors, keywords: editing.keywords, min_value_inr: editing.min_value_inr } : fromUrl),
    [editing, fromUrl],
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink">Email alerts</h1>
          <p className="mt-1 max-w-2xl text-ink-2">
            Get an email when a tender opens in your area. For example, everything in Chhattisgarh, or only road and building work around Bhilai.
          </p>
        </div>
        {me?.authenticated && !showForm && (
          <Button variant="primary" onClick={() => setMode("new")}>
            <Plus className="size-4" /> New alert
          </Button>
        )}
      </div>

      {loading ? (
        <Skeleton className="h-80 w-full rounded-2xl" />
      ) : (
        <>
          {showForm && (
            <Card className="mb-10 p-5 sm:p-8">
              <h2 className="mb-6 text-lg font-semibold text-ink">{editing ? `Edit “${editing.name}”` : "New alert"}</h2>
              <AlertForm
                initial={initial}
                editing={editing}
                onSaved={() => setMode(null)}
                onCancel={me?.authenticated && (alerts.data?.length ?? 0) > 0 ? () => setMode(null) : undefined}
              />
            </Card>
          )}

          {me?.authenticated && (
            <section>
              <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-ink">
                <Mail className="size-5 text-brand" /> Your alerts
                <span className="text-sm font-normal text-ink-3">sent to {me.user?.email}</span>
              </h2>
              {alerts.isLoading ? (
                <Skeleton className="h-32 w-full rounded-2xl" />
              ) : alerts.data?.length ? (
                <div className="grid gap-3 md:grid-cols-2">
                  {alerts.data.map((a) => (
                    <AlertRow key={a.id} a={a} onEdit={() => (setMode(a), window.scrollTo({ top: 0, behavior: "smooth" }))} />
                  ))}
                </div>
              ) : (
                <EmptyState icon={<BellRing className="size-6" />} title="No alerts yet">
                  Create your first alert above.
                </EmptyState>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
