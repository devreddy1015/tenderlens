import { LockKeyhole } from "lucide-react";
import type { ReactNode } from "react";
import { GoogleButton, useAuth } from "../lib/auth";
import { Card, Dialog, Skeleton } from "./ui";

/** Why to sign in, and Google's button. */
export function SignInCard({ title, children, onDone }: { title: string; children?: ReactNode; onDone?: () => void }) {
  return (
    <Card ticks className="mx-auto max-w-xl p-6 sm:p-8">
      <p className="label flex items-center gap-2">
        <LockKeyhole className="size-3.5 text-signal-text" aria-hidden="true" /> Sign in
      </p>
      <h2 className="mt-3 text-xl font-semibold text-ink">{title}</h2>
      {children && <div className="mt-2 text-sm text-ink-2">{children}</div>}
      <div className="mt-6">
        <GoogleButton onDone={onDone} />
      </div>
    </Card>
  );
}

/** Children for signed-in people; a sign-in card for everyone else. */
export function SignInGate({ title, pitch, children }: { title: string; pitch?: ReactNode; children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Skeleton className="mt-8 h-72 w-full rounded-lg" />;
  if (!me?.authenticated) {
    return (
      <div className="mt-10">
        <SignInCard title={title}>{pitch}</SignInCard>
      </div>
    );
  }
  return <>{children}</>;
}

export function SignInDialog({ open, onClose, title, children, onDone }: { open: boolean; onClose: () => void; title: string; children?: ReactNode; onDone?: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Sign in">
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="mt-1 text-sm text-ink-2">{children}</div>}
      <div className="mt-5">
        <GoogleButton
          onDone={() => {
            onClose();
            onDone?.();
          }}
        />
      </div>
    </Dialog>
  );
}
