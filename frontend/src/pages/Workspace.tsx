import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Mail, ShieldAlert, Trash2, UserPlus } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useLocation } from "react-router";
import { MultiPicker, SectorToggles } from "../components/MultiPicker";
import { SignInGate } from "../components/SignIn";
import { UpgradeNotice } from "../components/Upgrade";
import { UsageMeters } from "../components/UsageMeters";
import { Button, ButtonLink, Card, cx, EmptyState, Field, inputClass, PageHeader, Skeleton, Tag } from "../components/ui";
import { api, ApiError, errorMessage, type NewApiKey, quotaExceeded, type Role, type Workspace, type WorkspacePatch } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate, formatInr } from "../lib/format";
import { byPrice, includes } from "../lib/plans";
import { useMembers, usePlans, useSubscription, useWorkspace } from "../lib/queries";
import { INDIAN_STATES } from "../lib/states";
import { useToast } from "../lib/toast";

/** Common Indian bidder credentials; anything else can be typed in. */
const CERTIFICATIONS = [
  "MSE (Udyam registered)",
  "Startup (DPIIT)",
  "NSIC registered",
  "ISO 9001",
  "ISO 14001",
  "ISO 45001",
  "ISO 27001",
  "CMMI Level 3",
  "Class-A contractor",
  "Class-B contractor",
  "Electrical contractor licence",
  "BIS licence",
  "Women-owned business",
  "SC/ST-owned MSE",
];

const ROLE_LABEL: Record<Role, string> = { owner: "Owner", admin: "Admin", member: "Member" };

function Section({ id, index, title, hint, children, aside }: { id: string; index: string; title: string; hint?: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-line py-10 first:border-t-0 first:pt-2">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-2xl">
          <p className="label mb-2 flex items-center gap-3">
            <span className="text-signal-text">{index}</span>
            <span className="h-px w-6 bg-line-strong" aria-hidden="true" />
            {title}
          </p>
          {hint && <p className="text-sm text-ink-2">{hint}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** Rupee amounts are typed as plain digits; the hint reads them back in lakh/crore. */
function AmountInput({ value, onChange, disabled, label, hint, error }: { value: string; onChange: (v: string) => void; disabled: boolean; label: string; hint: string; error?: string }) {
  const ok = value === "" || /^\d{1,15}(\.\d{1,2})?$/.test(value);
  return (
    <Field label={label} hint={value && ok ? `${formatInr(value)} · ${hint}` : hint} error={error ?? (ok ? undefined : "Rupees in digits, e.g. 25000000")}>
      <input value={value} onChange={(e) => onChange(e.target.value.replace(/[,\s₹]/g, ""))} inputMode="decimal" disabled={disabled} className={cx(inputClass, "num disabled:opacity-60")} placeholder="0" />
    </Field>
  );
}

const amountText = (v: string | null) => (v === null || v === "" ? "" : String(Number(v)));

function ProfileForm({ ws, canEdit }: { ws: Workspace; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const initial = () => ({
    name: ws.name,
    gstin: ws.profile.gstin ?? "",
    annual_turnover_inr: amountText(ws.profile.annual_turnover_inr),
    largest_similar_work_inr: amountText(ws.profile.largest_similar_work_inr),
    years_in_business: ws.profile.years_in_business === null ? "" : String(ws.profile.years_in_business),
    states: ws.profile.states ?? [],
    sectors: ws.profile.sectors ?? [],
    certifications: ws.profile.certifications ?? [],
  });
  const [d, setD] = useState(initial);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  // Reset the form when the saved profile changes (after a save, or a teammate's edit), not on
  // every refetch: usage counters refresh the workspace often.
  const saved = JSON.stringify([ws.name, ws.profile]);
  const [seen, setSeen] = useState(saved);
  if (saved !== seen) {
    setSeen(saved);
    setD(initial());
  }

  const save = useMutation({
    mutationFn: () => {
      const patch: WorkspacePatch = {
        name: d.name.trim(),
        gstin: d.gstin.trim().toUpperCase(),
        annual_turnover_inr: d.annual_turnover_inr || null,
        largest_similar_work_inr: d.largest_similar_work_inr || null,
        years_in_business: d.years_in_business === "" ? null : Number(d.years_in_business),
        states: d.states,
        sectors: d.sectors,
        certifications: d.certifications,
      };
      return api.workspace.update(patch);
    },
    onSuccess: (next) => {
      if (next && typeof next === "object" && "profile" in next) qc.setQueryData(["workspace"], next);
      qc.invalidateQueries({ queryKey: ["workspace"] });
      // Eligibility compares tenders with this profile.
      qc.invalidateQueries({ queryKey: ["copilot", "eligibility"] });
      setErrors({});
      toast("success", "Company profile saved");
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors(e.fields);
      toast("error", errorMessage(e, "Couldn't save the profile"));
    },
  });
  const err = (k: string) => errors[k]?.[0];
  const gstinOk = d.gstin === "" || /^[0-9A-Z]{15}$/i.test(d.gstin.trim());

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (gstinOk) save.mutate();
      }}
    >
      <Card className="p-5 sm:p-6">
        <fieldset disabled={!canEdit} className="grid gap-5 md:grid-cols-2">
          <Field label="Company name" error={err("name")}>
            <input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} required maxLength={200} className={cx(inputClass, "disabled:opacity-60")} />
          </Field>
          <Field label="GSTIN" hint="15 characters, optional" error={err("gstin") ?? (gstinOk ? undefined : "A GSTIN has 15 letters and digits.")}>
            <input value={d.gstin} onChange={(e) => setD({ ...d, gstin: e.target.value.toUpperCase().slice(0, 15) })} className={cx(inputClass, "num uppercase disabled:opacity-60")} placeholder="22AAAAA0000A1Z5" />
          </Field>
          <AmountInput
            label="Average annual turnover (₹)"
            hint="average of the last 3 financial years"
            value={d.annual_turnover_inr}
            onChange={(v) => setD({ ...d, annual_turnover_inr: v })}
            disabled={!canEdit}
            error={err("annual_turnover_inr")}
          />
          <AmountInput
            label="Largest similar work completed (₹)"
            hint="value of your biggest comparable contract"
            value={d.largest_similar_work_inr}
            onChange={(v) => setD({ ...d, largest_similar_work_inr: v })}
            disabled={!canEdit}
            error={err("largest_similar_work_inr")}
          />
          <Field label="Years in business" error={err("years_in_business")}>
            <input
              value={d.years_in_business}
              onChange={(e) => setD({ ...d, years_in_business: e.target.value.replace(/\D/g, "").slice(0, 3) })}
              inputMode="numeric"
              className={cx(inputClass, "num disabled:opacity-60")}
              placeholder="e.g. 8"
            />
          </Field>
          <div className="hidden md:block" aria-hidden="true" />
          <div className="md:col-span-2">
            <Field label="States you work in" hint="Alerts default to these." error={err("states")}>
              <MultiPicker
                value={d.states}
                onChange={(states) => setD({ ...d, states })}
                options={INDIAN_STATES}
                label="Add a state"
                placeholder="Type a state, e.g. Chhattisgarh"
                morePlaceholder="Add another state"
                disabled={!canEdit}
              />
            </Field>
          </div>
          <div className="md:col-span-2">
            <span className="mb-1.5 block text-sm font-medium text-ink">Kinds of work</span>
            <SectorToggles value={d.sectors} onChange={(sectors) => setD({ ...d, sectors })} disabled={!canEdit} />
            {err("sectors") && <span className="mt-1.5 block text-xs text-critical">{err("sectors")}</span>}
          </div>
          <div className="md:col-span-2">
            <Field label="Certifications and registrations" hint="Eligibility checks look for these, e.g. MSE exemption from EMD." error={err("certifications")}>
              <MultiPicker
                value={d.certifications}
                onChange={(certifications) => setD({ ...d, certifications })}
                options={CERTIFICATIONS}
                label="Add a certification"
                placeholder="Type or pick, e.g. ISO 9001"
                morePlaceholder="Add another"
                allowCustom
                disabled={!canEdit}
              />
            </Field>
          </div>
        </fieldset>
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
          <p className="text-xs text-ink-3">{canEdit ? "Used for eligibility checks. Visible to your team only." : "Only owners and admins can change the profile."}</p>
          {canEdit && (
            <Button type="submit" variant="primary" disabled={save.isPending || !gstinOk}>
              {save.isPending ? "Saving…" : "Save profile"}
            </Button>
          )}
        </div>
      </Card>
    </form>
  );
}

function Team({ ws, canEdit }: { ws: Workspace; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const members = useMembers();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [confirm, setConfirm] = useState<number | null>(null);
  const invite = useMutation({
    mutationFn: () => api.workspace.invite(email.trim(), role),
    onSuccess: () => {
      toast("success", `Invite sent to ${email.trim()}`);
      setEmail("");
      qc.invalidateQueries({ queryKey: ["members"] });
    },
    onError: (e) => {
      if (!quotaExceeded(e)) toast("error", errorMessage(e, "Couldn't send the invite"));
    },
  });
  const remove = useMutation({
    mutationFn: api.workspace.removeMember,
    onSuccess: () => {
      setConfirm(null);
      qc.invalidateQueries({ queryKey: ["members"] });
      qc.invalidateQueries({ queryKey: ["workspace"] });
      toast("success", "Removed from the workspace");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't remove them")),
  });
  const seats = ws.plan.limits.seats;
  const quota = quotaExceeded(invite.error);
  const fieldErr = invite.error instanceof ApiError ? (invite.error.fields.email?.[0] ?? invite.error.fields.role?.[0]) : undefined;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <Card className="overflow-hidden">
        {members.isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : members.isError ? (
          <p className="p-4 text-sm text-critical">{errorMessage(members.error)}</p>
        ) : (
          <ul className="divide-y divide-line">
            {members.data?.map((m) => {
              const self = m.email === me?.user?.email;
              return (
                <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <span className="num grid size-8 shrink-0 place-items-center rounded-md border border-line bg-surface-2 text-sm text-ink">{(m.name || m.email)[0]?.toUpperCase()}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {m.name || m.email} {self && <span className="font-normal text-ink-3">(you)</span>}
                    </p>
                    <p className="num truncate text-xs text-ink-3">
                      {m.email} · joined {formatDate(m.joined_at, false)}
                    </p>
                  </div>
                  <Tag tone={m.role === "owner" ? "signal" : undefined}>{ROLE_LABEL[m.role] ?? m.role}</Tag>
                  {canEdit &&
                    !self &&
                    m.role !== "owner" &&
                    (confirm === m.id ? (
                      <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
                        Remove?
                        <Button size="sm" variant="danger" className="h-7" onClick={() => remove.mutate(m.id)} disabled={remove.isPending}>
                          Remove
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7" onClick={() => setConfirm(null)}>
                          Keep
                        </Button>
                      </span>
                    ) : (
                      <button type="button" onClick={() => setConfirm(m.id)} className="text-ink-3 hover:text-critical" aria-label={`Remove ${m.email}`}>
                        <Trash2 className="size-4" />
                      </button>
                    ))}
                </li>
              );
            })}
          </ul>
        )}
        <p className="num border-t border-line px-4 py-2.5 text-xs text-ink-3">
          {members.data?.length ?? "–"} of {seats === null ? "unlimited" : (seats ?? 1)} seats used
        </p>
      </Card>

      <Card className="p-5">
        <p className="label flex items-center gap-2">
          <UserPlus className="size-3.5 text-signal-text" aria-hidden="true" /> Invite a teammate
        </p>
        {canEdit ? (
          <form
            className="mt-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              invite.mutate();
            }}
          >
            <Field label="Email" error={fieldErr}>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} placeholder="colleague@company.com" />
            </Field>
            <Field label="Role" hint={role === "admin" ? "Admins manage the profile, team, billing and API keys." : "Members use search, the Copilot and the pipeline."}>
              <select value={role} onChange={(e) => setRole(e.target.value as Role)} className={inputClass}>
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </select>
            </Field>
            <Button type="submit" variant="primary" className="w-full" disabled={invite.isPending}>
              <Mail className="size-4" aria-hidden="true" /> {invite.isPending ? "Sending…" : "Send invite"}
            </Button>
            {quota && <UpgradeNotice limit={quota.limit} message={quota.message} />}
            <p className="text-xs text-ink-3">They get an email with a link that signs them in to this workspace.</p>
          </form>
        ) : (
          <p className="mt-3 text-sm text-ink-2">Ask an owner or admin to invite people.</p>
        )}
      </Card>
    </div>
  );
}

function Billing({ ws, canEdit }: { ws: Workspace; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const sub = useSubscription();
  const [confirm, setConfirm] = useState(false);
  const cancel = useMutation({
    mutationFn: api.billing.cancel,
    onSuccess: () => {
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["subscription"] });
      qc.invalidateQueries({ queryKey: ["workspace"] });
      toast("success", "Subscription cancelled");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't cancel the subscription")),
  });
  const s = sub.data;
  const paid = ws.plan.code !== "free" && (Number(ws.plan.price_inr_month) > 0 || ws.plan.price_inr_month === null);
  const cancelled = s && /cancel/i.test(s.status);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
      <Card ticks className="p-5">
        <p className="label">Plan</p>
        <div className="mt-3 flex flex-wrap items-baseline gap-3">
          <p className="text-2xl font-semibold text-ink">{ws.plan.name}</p>
          {s && <Tag tone={s.status === "active" ? "good" : cancelled ? "critical" : undefined}>{s.status}</Tag>}
        </div>
        {sub.isLoading ? (
          <Skeleton className="mt-4 h-16 w-full" />
        ) : s ? (
          <dl className="mt-4 space-y-1.5 text-sm">
            {s.interval && (
              <div className="flex justify-between gap-4">
                <dt className="text-ink-3">Billed</dt>
                <dd className="text-ink-2">{s.interval === "year" ? "Yearly" : "Monthly"}</dd>
              </div>
            )}
            {s.current_period_end && (
              <div className="flex justify-between gap-4">
                <dt className="text-ink-3">{cancelled ? "Ends" : "Renews"}</dt>
                <dd className="num text-ink-2">{formatDate(s.current_period_end, false)}</dd>
              </div>
            )}
            {s.provider && (
              <div className="flex justify-between gap-4">
                <dt className="text-ink-3">Payments</dt>
                <dd className="text-ink-2 capitalize">{s.provider}</dd>
              </div>
            )}
          </dl>
        ) : null}
        <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4">
          <ButtonLink to="/pricing" variant={paid ? "secondary" : "primary"}>
            {paid ? "Change plan" : "Upgrade"}
          </ButtonLink>
          {canEdit &&
            paid &&
            !cancelled &&
            (confirm ? (
              <span className="inline-flex flex-wrap items-center gap-1.5 text-sm text-ink-2">
                Back to Free?
                <Button variant="danger" size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                  {cancel.isPending ? "Cancelling…" : "Cancel subscription"}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirm(false)}>
                  Keep it
                </Button>
              </span>
            ) : (
              <Button variant="ghost" onClick={() => setConfirm(true)}>
                Cancel subscription
              </Button>
            ))}
        </div>
      </Card>
      <Card className="p-5">
        <p className="label mb-4">Usage</p>
        <UsageMeters keys={["questions_per_month", "documents_per_month", "alerts", "seats"]} />
        <p className="mt-4 text-xs text-ink-3">Monthly counters reset on the 1st.</p>
      </Card>
    </div>
  );
}

function ApiKeys({ ws, canEdit }: { ws: Workspace; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const plans = usePlans();
  const allowed = includes(ws.plan, "api");
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: api.workspace.apiKeys, enabled: allowed });
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<NewApiKey | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState<number | null>(null);
  const create = useMutation({
    mutationFn: () => api.workspace.createApiKey(name.trim() || "API key"),
    onSuccess: (k) => {
      setFresh(k);
      setName("");
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (e) => {
      if (!quotaExceeded(e)) toast("error", errorMessage(e, "Couldn't create the key"));
    },
  });
  const del = useMutation({
    mutationFn: api.workspace.deleteApiKey,
    onSuccess: () => {
      setConfirm(null);
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      toast("success", "Key revoked");
    },
    onError: (e) => toast("error", errorMessage(e, "Couldn't revoke the key")),
  });
  const origin = typeof window !== "undefined" ? window.location.origin : "";

  if (!allowed) {
    const withApi = byPrice(plans.data ?? []).find((p) => includes(p, "api"));
    return (
      <EmptyState icon={<KeyRound className="size-5" />} title="API access isn't on your plan">
        {withApi ? `It comes with the ${withApi.name} plan.` : "It comes with a higher plan."} The OCDS release feed at{" "}
        <a href="/api/ocds/releases" className="num text-ink underline decoration-line-strong underline-offset-4">
          /api/ocds/releases
        </a>{" "}
        is open to everyone.
        <div className="mt-4">
          <ButtonLink to="/pricing" size="sm">
            See plans
          </ButtonLink>
        </div>
      </EmptyState>
    );
  }
  const quota = quotaExceeded(create.error);

  return (
    <div className="space-y-4">
      {fresh && (
        <div className="rounded-lg border border-signal/50 bg-signal-soft p-4" role="status">
          <p className="flex items-center gap-2 text-sm font-medium text-ink">
            <ShieldAlert className="size-4 text-signal-text" aria-hidden="true" /> Copy your new key now. You won't see it again.
          </p>
          <div className="mt-3 flex items-center gap-2">
            <code className="num min-w-0 flex-1 overflow-x-auto rounded-md border border-line bg-surface px-3 py-2 text-[13px] whitespace-nowrap text-ink">{fresh.key}</code>
            <Button
              size="sm"
              onClick={() =>
                navigator.clipboard?.writeText(fresh.key).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                })
              }
            >
              {copied ? <Check className="size-3.5 text-good" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <Button size="sm" variant="ghost" className="mt-2" onClick={() => setFresh(null)}>
            I've stored it safely
          </Button>
        </div>
      )}
      <Card className="overflow-hidden">
        {keys.isLoading ? (
          <Skeleton className="m-4 h-12" />
        ) : keys.data?.length ? (
          <ul className="divide-y divide-line">
            {keys.data.map((k) => (
              <li key={k.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <KeyRound className="size-4 shrink-0 text-ink-3" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{k.name}</p>
                  <p className="num text-xs text-ink-3">
                    {k.prefix ? `${k.prefix}… · ` : ""}created {formatDate(k.created_at, false)}
                    {k.last_used_at !== undefined && ` · ${k.last_used_at ? `last used ${formatDate(k.last_used_at)}` : "never used"}`}
                  </p>
                </div>
                {canEdit &&
                  (confirm === k.id ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
                      Revoke? Apps using it stop working.
                      <Button size="sm" variant="danger" className="h-7" onClick={() => del.mutate(k.id)} disabled={del.isPending}>
                        Revoke
                      </Button>
                      <Button size="sm" variant="ghost" className="h-7" onClick={() => setConfirm(null)}>
                        Keep
                      </Button>
                    </span>
                  ) : (
                    <button type="button" onClick={() => setConfirm(k.id)} className="text-ink-3 hover:text-critical" aria-label={`Revoke ${k.name}`}>
                      <Trash2 className="size-4" />
                    </button>
                  ))}
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-4 text-sm text-ink-3">No keys yet.</p>
        )}
        {canEdit && (
          <form
            className="flex flex-wrap items-end gap-2 border-t border-line p-4"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <div className="min-w-48 flex-1">
              <Field label="New key name">
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} className={inputClass} placeholder="e.g. ERP sync" />
              </Field>
            </div>
            <Button type="submit" disabled={create.isPending}>
              <KeyRound className="size-4" aria-hidden="true" /> {create.isPending ? "Creating…" : "Create key"}
            </Button>
          </form>
        )}
        {quota && <UpgradeNotice limit={quota.limit} message={quota.message} className="m-4 mt-0" />}
      </Card>
      <div className="rounded-md border border-line bg-surface-2/60 p-4">
        <p className="label mb-2">Usage</p>
        <pre className="num overflow-x-auto text-[12.5px] leading-relaxed text-ink-2">
          {`curl -H "Authorization: Api-Key <your key>" \\\n  "${origin}/api/tenders?q=road&state=Odisha"`}
        </pre>
        <p className="mt-2 text-xs text-ink-3">
          Same filters as Explore. Reference:{" "}
          <a href="/api/docs/" className="text-ink underline decoration-line-strong underline-offset-4">
            API documentation
          </a>
          . Every record carries its source portal; keep the attribution when you show the data.
        </p>
      </div>
    </div>
  );
}

function WorkspaceBody() {
  const ws = useWorkspace();
  const loc = useLocation();
  // Deep links such as /workspace#profile (from the eligibility panel) land on their section
  // once it has rendered.
  useEffect(() => {
    if (!ws.data || !loc.hash) return;
    document.getElementById(loc.hash.slice(1))?.scrollIntoView?.({ block: "start" });
  }, [ws.data, loc.hash]);

  if (ws.isLoading) return <Skeleton className="mt-8 h-96 w-full rounded-lg" />;
  if (ws.isError || !ws.data)
    return (
      <div className="mt-8">
        <EmptyState icon={<ShieldAlert className="size-5" />} title="Couldn't load your workspace">
          {errorMessage(ws.error)}
        </EmptyState>
      </div>
    );
  const w = ws.data;
  const canEdit = w.role === "owner" || w.role === "admin";
  return (
    <>
      <div className="mt-6 flex flex-wrap items-center gap-2 text-sm">
        <Tag tone="signal">{w.plan.name} plan</Tag>
        <Tag>You are {ROLE_LABEL[w.role]?.toLowerCase() ?? w.role}</Tag>
        <nav aria-label="Workspace sections" className="ml-auto flex flex-wrap gap-1">
          {[
            ["profile", "Profile"],
            ["team", "Team"],
            ["billing", "Billing & usage"],
            ["api", "API keys"],
          ].map(([id, label]) => (
            <a key={id} href={`#${id}`} className="rounded-md px-2.5 py-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink">
              {label}
            </a>
          ))}
        </nav>
      </div>
      <div className="mt-8">
        <Section id="profile" index="01" title="Company profile" hint="What you can bid for. The Copilot's eligibility check compares each tender's requirements with this.">
          <ProfileForm ws={w} canEdit={canEdit} />
        </Section>
        <Section id="team" index="02" title="Team" hint="Everyone here shares the pipeline, the documents and the plan's limits.">
          <Team ws={w} canEdit={canEdit} />
        </Section>
        <Section id="billing" index="03" title="Billing & usage">
          <Billing ws={w} canEdit={canEdit} />
        </Section>
        <Section id="api" index="04" title="API keys" hint="For your own systems: the same tender search as a JSON API.">
          <ApiKeys ws={w} canEdit={canEdit} />
        </Section>
      </div>
    </>
  );
}

export default function WorkspacePage() {
  const ws = useWorkspace();
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageHeader kicker="Workspace" title={ws.data?.name ?? "Workspace"}>
        Your company profile, team, plan and API keys.
      </PageHeader>
      <SignInGate title="Sign in to your workspace" pitch="Your workspace holds your company profile, your team, your plan and your API keys.">
        <WorkspaceBody />
      </SignInGate>
    </div>
  );
}
