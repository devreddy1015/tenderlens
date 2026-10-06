import { X } from "lucide-react";
import { type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ReactNode, useEffect, useRef } from "react";
import { Link, type LinkProps } from "react-router";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";
type ButtonStyle = { variant?: Variant; size?: Size; className?: string; children?: ReactNode };

function buttonClass(variant: Variant, size: Size, className?: string) {
  return cx("btn", `btn-${variant}`, `btn-${size}`, className);
}

/** Primary buttons carry the spinning border beam (see .btn-primary in index.css). */
function ButtonBody({ variant, children }: { variant: Variant; children?: ReactNode }) {
  if (variant !== "primary") return <>{children}</>;
  return (
    <>
      <span className="btn-beam" aria-hidden="true" />
      <span className="btn-face">{children}</span>
    </>
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & ButtonStyle) {
  return (
    <button {...props} className={buttonClass(variant, size, className)}>
      <ButtonBody variant={variant}>{children}</ButtonBody>
    </button>
  );
}

/** A router link that looks like a Button. */
export function ButtonLink({ variant = "secondary", size = "md", className, children, ...props }: LinkProps & ButtonStyle) {
  return (
    <Link {...props} className={buttonClass(variant, size, className)}>
      <ButtonBody variant={variant}>{children}</ButtonBody>
    </Link>
  );
}

/** An external link that looks like a Button; opens in a new tab. */
export function ButtonAnchor({
  variant = "secondary",
  size = "md",
  className,
  children,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & ButtonStyle) {
  return (
    <a target="_blank" rel="noreferrer" {...props} className={buttonClass(variant, size, className)}>
      <ButtonBody variant={variant}>{children}</ButtonBody>
    </a>
  );
}

/** A bordered surface. `ticks` adds viewfinder registration marks at the corners. */
export function Card({ className, children, ticks }: { className?: string; children: ReactNode; ticks?: boolean }) {
  return <div className={cx("panel", ticks && "ticks", className)}>{children}</div>;
}

export function Tag({ children, className, tone }: { children: ReactNode; className?: string; tone?: "signal" | "good" | "critical" }) {
  return <span className={cx("tag", tone && `tag-${tone}`, className)}>{children}</span>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-md", className)} aria-hidden="true" />;
}

/** The top of a page: a mono kicker, the title, an optional description and actions. */
export function PageHeader({ kicker, title, children, actions }: { kicker?: string; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b border-line pb-6">
      <div className="max-w-3xl">
        {kicker && <p className="eyebrow mb-3">{kicker}</p>}
        <h1 className="text-3xl font-semibold text-ink sm:text-4xl">{title}</h1>
        {children && <div className="mt-2 text-[15px] text-ink-2">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** A numbered section heading: "01 — TENDER MAP", then the title. */
export function SectionHeading({
  index,
  label,
  title,
  action,
  children,
}: {
  index?: string;
  label?: string;
  title: string;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        {(index || label) && (
          <p className="label mb-3 flex items-center gap-3">
            {index && <span className="text-signal-text">{index}</span>}
            {index && label && <span className="h-px w-6 bg-line-strong" aria-hidden="true" />}
            {label}
          </p>
        )}
        <h2 className="text-2xl font-semibold text-ink sm:text-[28px] sm:leading-tight">{title}</h2>
        {children && <p className="mt-2 text-ink-2">{children}</p>}
      </div>
      {action}
    </div>
  );
}

/** A labelled number: mono label above, large tabular value below. */
export function Stat({ label, value, hint, className }: { label: string; value: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <dt className="label">{label}</dt>
      <dd className="num mt-2 text-2xl font-medium text-ink">{value}</dd>
      {hint && <dd className="mt-1 text-xs text-ink-3">{hint}</dd>}
    </div>
  );
}

/** A radiogroup of mutually exclusive options. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; title?: string }[];
  label: string;
  className?: string;
}) {
  return (
    <div className={cx("seg", className)} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} title={o.title} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={onChange} className="switch" />;
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="ticks flex flex-col items-center rounded-lg border border-dashed border-line-strong px-6 py-16 text-center">
      <div className="mb-4 grid size-11 place-items-center rounded-md border border-line bg-surface text-ink-3">{icon}</div>
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="mt-1.5 max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  );
}

/** Modal dialog on the native <dialog> element: focus trap, Esc and backdrop for free. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    if (!open && d.open) d.close?.();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className={cx(
        "m-auto w-[min(94vw,540px)] rounded-lg border border-line bg-surface p-0 text-ink shadow-panel backdrop:bg-black/60 backdrop:backdrop-blur-[2px]",
        wide && "w-[min(94vw,760px)]",
      )}
      aria-label={title}
    >
      {open && (
        <div>
          <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-3.5">
            <h2 className="text-[15px] font-semibold">{title}</h2>
            <button onClick={onClose} className="grid size-8 place-items-center rounded-md text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Close">
              <X className="size-4" />
            </button>
          </div>
          <div className="p-5">{children}</div>
        </div>
      )}
    </dialog>
  );
}

/** Input look without a size: use it with your own h-* / w-* (utilities of the same
 *  property in one class list don't reliably override each other). */
export const inputBase =
  "rounded-md border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-ink-3 transition-colors hover:border-ink-3 focus:border-signal focus:outline-none focus:ring-3 focus:ring-signal/20";
export const inputClass = `h-10 w-full ${inputBase}`;

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && !error && <span className="mt-1.5 block text-xs text-ink-3">{hint}</span>}
      {error && <span className="mt-1.5 block text-xs text-critical">{error}</span>}
    </label>
  );
}
