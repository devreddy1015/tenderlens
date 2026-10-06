import { Check, X } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { SECTORS, SectorIcon } from "../lib/sectors";
import { cx, inputClass } from "./ui";

/** A removable chip: a tag with an x button. */
export function Chip({ children, onRemove, removeLabel }: { children: ReactNode; onRemove?: () => void; removeLabel: string }) {
  return (
    <span className={cx("tag tag-signal h-7 pl-2", onRemove ? "pr-1" : "pr-2")}>
      {children}
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={removeLabel} className="grid size-5 place-items-center rounded-[3px] hover:bg-signal/15">
          <X className="size-3" />
        </button>
      )}
    </span>
  );
}

/** Pick several values from a list by typing: chips for the chosen ones, a filtered list
 *  for the rest. Enter adds the first match (or, with allowCustom, what was typed);
 *  Backspace in an empty box removes the last chip. */
export function MultiPicker({
  value,
  onChange,
  options,
  label,
  placeholder,
  morePlaceholder = "Add another",
  allowCustom,
  disabled,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  options: string[];
  label: string;
  placeholder: string;
  morePlaceholder?: string;
  allowCustom?: boolean;
  disabled?: boolean;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const listId = useId();
  const typed = q.trim();
  const taken = (s: string) => value.some((v) => v.toLowerCase() === s.toLowerCase());
  const matches = options.filter((s) => !taken(s) && s.toLowerCase().includes(typed.toLowerCase()));
  const custom = allowCustom && typed && !taken(typed) && !matches.some((m) => m.toLowerCase() === typed.toLowerCase()) ? typed : null;
  const choices = custom ? [...matches, custom] : matches;
  const add = (s: string) => {
    onChange([...value, s]);
    setQ("");
  };

  return (
    <div className="relative">
      <div
        className={cx(
          inputClass,
          "flex h-auto min-h-10 flex-wrap items-center gap-1.5 px-1.5 py-1.5 focus-within:border-signal focus-within:ring-3 focus-within:ring-signal/20",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        {value.map((s) => (
          <Chip key={s} onRemove={disabled ? undefined : () => onChange(value.filter((x) => x !== s))} removeLabel={`Remove ${s}`}>
            {s}
          </Chip>
        ))}
        <input
          value={q}
          disabled={disabled}
          onChange={(e) => (setQ(e.target.value), setOpen(true))}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && choices[0]) {
              e.preventDefault();
              add(choices[0]);
            } else if (e.key === "Backspace" && !q && value.length) {
              onChange(value.slice(0, -1));
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          placeholder={value.length ? morePlaceholder : placeholder}
          className="h-7 min-w-40 flex-1 bg-transparent px-1.5 text-sm placeholder:text-ink-3 focus:outline-none"
          aria-label={label}
          role="combobox"
          aria-expanded={open && choices.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
        />
      </div>
      {open && choices.length > 0 && (
        <ul id={listId} className="absolute z-20 mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-line-strong bg-surface p-1 shadow-panel" role="listbox">
          {choices.map((s) => (
            <li key={s} role="option" aria-selected={false}>
              <button
                type="button"
                tabIndex={-1}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => add(s)}
                className="w-full rounded px-2.5 py-2 text-left text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
              >
                {s === custom ? (
                  <>
                    Add “<span className="text-ink">{s}</span>”
                  </>
                ) : (
                  s
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Every sector as a toggle button; none selected means all of them. */
export function SectorToggles({ value, onChange, disabled }: { value: string[]; onChange: (v: string[]) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Sectors">
      {SECTORS.map((s) => {
        const on = value.includes(s.slug);
        return (
          <button
            type="button"
            key={s.slug}
            aria-pressed={on}
            disabled={disabled}
            onClick={() => onChange(on ? value.filter((x) => x !== s.slug) : [...value, s.slug])}
            className={cx(
              "tag h-9 px-2.5 text-[13px] transition-colors disabled:opacity-60 sm:h-8",
              on ? "tag-signal" : "text-ink-2 hover:border-line-strong hover:text-ink",
            )}
          >
            {on ? <Check className="size-3.5" aria-hidden="true" /> : <SectorIcon slug={s.slug} className="size-3.5 text-ink-3" />}
            {s.label}
          </button>
        );
      })}
    </div>
  );
}
