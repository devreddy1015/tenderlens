import {
  Building2,
  ClipboardList,
  Cpu,
  Droplets,
  FlaskConical,
  HeartPulse,
  type LucideIcon,
  Package,
  Route,
  Shapes,
  ShieldCheck,
  Truck,
  Users,
  Zap,
} from "lucide-react";

/** Sector identity is icon + label, never colour alone: 13 sectors is more than any
 *  categorical palette can keep apart. Mirrors tenders/sectors.py on the backend. */
export const SECTORS: { slug: string; label: string; icon: LucideIcon }[] = [
  { slug: "roads", label: "Roads & Bridges", icon: Route },
  { slug: "buildings", label: "Buildings & Civil", icon: Building2 },
  { slug: "electrical", label: "Electrical & Power", icon: Zap },
  { slug: "water", label: "Water & Sanitation", icon: Droplets },
  { slug: "it", label: "IT & Technology", icon: Cpu },
  { slug: "security", label: "Security & Safety", icon: ShieldCheck },
  { slug: "health", label: "Health & Medical", icon: HeartPulse },
  { slug: "lab", label: "Science & Lab", icon: FlaskConical },
  { slug: "facility", label: "Facility & Manpower", icon: Users },
  { slug: "transport", label: "Vehicles & Transport", icon: Truck },
  { slug: "consultancy", label: "Consultancy & Surveys", icon: ClipboardList },
  { slug: "supplies", label: "Goods & Supplies", icon: Package },
  { slug: "other", label: "Other", icon: Shapes },
];

const BY_SLUG = Object.fromEntries(SECTORS.map((s) => [s.slug, s]));

export function sectorMeta(slug: string | null | undefined) {
  return BY_SLUG[slug ?? ""] ?? BY_SLUG.other;
}

export function SectorIcon({ slug, className = "size-4" }: { slug: string; className?: string }) {
  const Icon = sectorMeta(slug).icon;
  return <Icon className={className} aria-hidden="true" />;
}
