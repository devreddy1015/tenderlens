import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, MapPin, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Chip, MultiPicker, SectorToggles } from "../components/MultiPicker";
import { Button, Card, cx, EmptyState, Field, inputClass, PageHeader, Skeleton, Switch } from "../components/ui";
import { type Alert, type AlertCriteria, ApiError, api, quotaExceeded } from "../lib/api";
import { GoogleButton, useAuth } from "../lib/auth";
import { formatCount, formatDate, formatInr } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import { SECTORS, SectorIcon, sectorMeta } from "../lib/sectors";
import { INDIAN_STATES } from "../lib/states";
import { useToast } from "../lib/toast";

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

/** One numbered step of the alert builder: a mono index on the left, the fields on the right. */
function Step({ index, title, hint, children }: { index: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="grid gap-x-6 gap-y-4 border-b border-line py-7 first:pt-0 last:border-0 last:pb-0 sm:grid-cols-[3.5rem_1fr]">
      <div className="flex items-baseline gap-3 sm:block">
        <p className="num text-sm text-signal-text">{index}</p>
        <div className="h-px w-6 bg-line-strong sm:mt-3" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <h3 className="text-[15px] font-medium text-ink">{title}</h3>
        {hint && <p className="mt-0.5 text-sm text-ink-3">{hint}</p>}
        <div className="mt-4 space-y-4">{children}</div>
      </div>
    </section>
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
  useEffect(() => {
    setD(initial);
  }, [initial]);

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
      if (quotaExceeded(e)) return; // the upgrade dialog opens (lib/queryClient.ts)
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
    <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
      <form
        id="alert-form"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Step index="01" title="Where" hint="States, PIN areas, or both. Leave empty for all of India.">
          <Field label="States" error={errors.states?.[0]}>
            <MultiPicker
              value={d.states}
              onChange={(states) => setD({ ...d, states })}
              options={INDIAN_STATES}
              label="Add a state"
              placeholder="Type a state, e.g. Chhattisgarh"
              morePlaceholder="Add another state"
            />
          </Field>
          <div>
            <span className="mb-1.5 block text-sm font-medium text-ink">PIN areas</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {d.pin_prefixes.map((p) => (
                <Chip key={p} onRemove={() => setD({ ...d, pin_prefixes: d.pin_prefixes.filter((x) => x !== p) })} removeLabel={`Remove PIN ${p}`}>
                  <MapPin className="size-3" aria-hidden="true" />
                  {PIN_SHORTCUTS.find((s) => s.pin === p)?.label ?? "PIN"} <span className="num">{p}xxx</span>
                </Chip>
              ))}
              <span className="w-32">
                <input
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addPin(pin))}
                  inputMode="numeric"
                  placeholder="PIN prefix"
                  className={cx(inputClass, "num h-9")}
                  aria-label="PIN code prefix"
                />
              </span>
              <Button type="button" size="sm" className="h-9" onClick={() => addPin(pin)} disabled={pin.length < 2}>
                <Plus className="size-3.5" /> Add
              </Button>
            </div>
            {PIN_SHORTCUTS.some((s) => !d.pin_prefixes.includes(s.pin)) && (
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                <span className="label mr-1">Quick add</span>
                {PIN_SHORTCUTS.filter((s) => !d.pin_prefixes.includes(s.pin)).map((s) => (
                  <button
                    type="button"
                    key={s.pin}
                    onClick={() => addPin(s.pin)}
                    className="tag h-7 border-dashed bg-transparent text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
                  >
                    <Plus className="size-3 text-ink-3" aria-hidden="true" />
                    {s.label} <span className="num text-ink-3">{s.pin}</span>
                  </button>
                ))}
              </div>
            )}
            {errors.pin_prefixes && <p className="mt-1.5 text-xs text-critical">{errors.pin_prefixes[0]}</p>}
            <p className="mt-2 text-xs text-ink-3">The first 3 digits of a PIN code cover a district: 490 is Bhilai and Durg.</p>
          </div>
        </Step>

        <Step index="02" title="What kind of work" hint="None selected means every sector.">
          <SectorToggles value={d.sectors} onChange={(sectors) => setD({ ...d, sectors })} />
        </Step>

        <Step index="03" title="Refine" hint="Optional. Narrow the alert to the tenders worth your time.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Keywords" hint="Comma-separated. Any one must appear in the title." error={errors.keywords?.[0]}>
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
        </Step>

        <Step index="04" title="Name">
          <Field label="Alert name" hint={`Leave empty to use “${suggestName(d)}”.`} error={errors.name?.[0]}>
            <input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} maxLength={120} placeholder={suggestName(d)} className={inputClass} />
          </Field>
          {errors.non_field_errors && <p className="text-sm text-critical">{errors.non_field_errors[0]}</p>}
        </Step>
      </form>

      <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        <Card ticks className="p-5">
          <p className="label flex items-center gap-2">
            <span className="live-dot" aria-hidden="true" /> Matching now
          </p>
          <p className={cx("num mt-3 text-5xl font-medium tracking-[-0.06em] text-ink transition-opacity", preview.isPlaceholderData && "opacity-50")} aria-live="polite">
            {preview.data ? formatCount(preview.data.count) : <Skeleton className="h-12 w-24" />}
          </p>
          <p className="mt-1 text-sm text-ink-3">open tenders fit this alert</p>
          {(preview.data?.sample.length ?? 0) > 0 && (
            <ul className="mt-5 border-t border-line">
              {preview.data?.sample.map((t) => (
                <li key={t.id} className="border-b border-line py-3 last:border-0">
                  <Link to={`/tenders/${t.id}`} className="line-clamp-2 text-sm font-medium text-ink decoration-line-strong underline-offset-4 hover:underline">
                    {t.title}
                  </Link>
                  <p className="num mt-1 text-xs text-ink-3">
                    {t.state || "India"} · {formatInr(t.value_inr, { short: true })}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-4 rounded-md bg-surface-2 px-3 py-2.5 text-xs text-ink-2">
            One email now with these, then one after each hourly crawl when new ones open. Nothing if nothing is new.
          </p>
        </Card>
        {me?.authenticated ? (
          <div className="flex gap-2">
            {onCancel && (
              <Button type="button" variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
            )}
            <Button type="submit" form="alert-form" variant="primary" size="lg" className="flex-1" disabled={save.isPending}>
              <BellRing className="size-4" /> {save.isPending ? "Saving…" : editing ? "Save changes" : "Create alert"}
            </Button>
          </div>
        ) : (
          <Card className="p-5">
            <p className="label">Step 05 · Sign in</p>
            <p className="mt-2.5 font-medium text-ink">Sign in to save this alert</p>
            <p className="mt-1 mb-4 text-sm text-ink-2">We email alerts to your Google account address. Your choices on the left are kept.</p>
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
    <article className={cx("panel flex flex-col transition-opacity", !a.active && "opacity-70")}>
      <div className="flex items-start justify-between gap-4 p-5">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-medium text-ink">
            <span className={cx("size-1.5 shrink-0 rounded-full", a.active ? "bg-good" : "bg-line-strong")} aria-hidden="true" />
            <span className="truncate">{a.name}</span>
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <span className="tag">
              <MapPin className="size-3 text-ink-3" aria-hidden="true" /> {where.length ? where.join(", ") : "All of India"}
            </span>
            {a.sectors.map((s) => (
              <span key={s} className="tag">
                <SectorIcon slug={s} className="size-3 text-ink-3" /> {sectorMeta(s).label}
              </span>
            ))}
            {a.keywords && <span className="tag">“{a.keywords}”</span>}
            {a.min_value_inr && <span className="tag num">≥ {formatInr(a.min_value_inr, { short: true })}</span>}
          </div>
          <p className="num mt-3 text-xs text-ink-3">{a.last_sent_at ? `Last email ${formatDate(a.last_sent_at)}` : "No email sent yet"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2.5">
          <span className="label">{a.active ? "On" : "Paused"}</span>
          <Switch checked={a.active} onChange={() => toggle.mutate()} label={`${a.active ? "Pause" : "Resume"} ${a.name}`} />
        </div>
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-1 border-t border-line px-2 py-1.5">
        <Button size="sm" variant="ghost" onClick={() => test.mutate()} disabled={test.isPending}>
          <Send className="size-3.5" /> {test.isPending ? "Sending…" : "Send test"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onEdit}>
          <Pencil className="size-3.5" /> Edit
        </Button>
        {confirm ? (
          <span className="ml-auto inline-flex items-center gap-1.5 pl-2 text-sm text-ink-2">
            Delete this alert?
            <Button size="sm" variant="danger" onClick={() => del.mutate()}>
              Delete
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
              Keep
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" className="ml-auto hover:!text-critical" onClick={() => setConfirm(true)}>
            <Trash2 className="size-3.5" /> Delete
          </Button>
        )}
      </div>
    </article>
  );
}

export default function Alerts() {
  const { me, loading } = useAuth();
  const [params] = useSearchParams();
  const fromUrl = useMemo<Draft>(
    () => ({
      ...EMPTY,
      states: params.getAll("state").filter((s) => INDIAN_STATES.includes(s)),
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
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader
        kicker="Alerts"
        title="Email alerts"
        actions={
          me?.authenticated && !showForm ? (
            <Button variant="primary" onClick={() => setMode("new")}>
              <Plus className="size-4" /> New alert
            </Button>
          ) : undefined
        }
      >
        Get an email when a tender opens in your area. For example, everything in Chhattisgarh, or only road and building work around Bhilai.
      </PageHeader>

      {loading ? (
        <Skeleton className="mt-8 h-80 w-full rounded-lg" />
      ) : (
        <>
          {showForm && (
            <Card className="mt-8 overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3.5 sm:px-8">
                <h2 className="text-[15px] font-medium text-ink">{editing ? `Edit “${editing.name}”` : "New alert"}</h2>
                <p className="label">{editing ? "Editing" : "4 steps · about a minute"}</p>
              </div>
              <div className="p-5 sm:p-8">
                <AlertForm
                  initial={initial}
                  editing={editing}
                  onSaved={() => setMode(null)}
                  onCancel={me?.authenticated && (alerts.data?.length ?? 0) > 0 ? () => setMode(null) : undefined}
                />
              </div>
            </Card>
          )}

          {me?.authenticated && (
            <section className="mt-12">
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-semibold text-ink">
                  Your alerts {alerts.data && <span className="num ml-1 text-sm font-normal text-ink-3">{alerts.data.length}</span>}
                </h2>
                <p className="num text-xs text-ink-3">sent to {me.user?.email}</p>
              </div>
              {alerts.isLoading ? (
                <Skeleton className="h-32 w-full rounded-lg" />
              ) : alerts.data?.length ? (
                <div className="grid gap-3 md:grid-cols-2">
                  {alerts.data.map((a) => (
                    <AlertRow key={a.id} a={a} onEdit={() => (setMode(a), window.scrollTo({ top: 0, behavior: "smooth" }))} />
                  ))}
                </div>
              ) : (
                <EmptyState icon={<BellRing className="size-5" />} title="No alerts yet">
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
