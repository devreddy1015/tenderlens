import { CheckCircle2, CircleAlert, X } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

type Toast = { id: number; kind: "success" | "error"; text: string };

const ToastContext = createContext<(kind: Toast["kind"], text: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="fixed bottom-16 left-1/2 z-50 flex w-[min(92vw,420px)] -translate-x-1/2 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`flex items-start gap-3 rounded-md border border-l-2 border-line-strong bg-surface px-4 py-3 text-sm shadow-panel ${t.kind === "success" ? "border-l-good" : "border-l-critical"}`}
          >
            {t.kind === "success" ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-good" aria-label="Done" />
            ) : (
              <CircleAlert className="mt-0.5 size-4 shrink-0 text-critical" aria-label="Error" />
            )}
            <span className="flex-1 text-ink">{t.text}</span>
            <button onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} aria-label="Dismiss" className="text-ink-3 hover:text-ink">
              <X className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
