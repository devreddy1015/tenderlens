import { Link } from "react-router";
import { cx } from "./ui";

/** The TenderLens mark: a viewfinder (four corner brackets) locked onto one node of a
 *  network, the amber one. Drawn on a 24-unit grid so it stays crisp from 16px up. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cx("shrink-0", className)} aria-hidden="true" fill="none">
      <path
        d="M3 8.5V3h5.5M15.5 3H21v5.5M21 15.5V21h-5.5M8.5 21H3v-5.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="square"
      />
      <path d="M8.6 15.4 14.6 9.4" stroke="currentColor" strokeOpacity="0.55" strokeWidth="1.3" />
      <circle cx="8.4" cy="15.6" r="1.35" fill="currentColor" />
      <circle cx="15" cy="9" r="2.4" fill="var(--signal)" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <Link to="/" className={cx("group flex items-center gap-2 text-ink", className)} aria-label="TenderLens home">
      <LogoMark className="size-[22px] transition-transform duration-300 group-hover:scale-105" />
      <span className="text-[16px] font-semibold tracking-[-0.03em]">TenderLens</span>
    </Link>
  );
}
