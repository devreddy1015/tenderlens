import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";
import { Button, cx, inputClass } from "../components/ui";
import { ApiError, api, type Me, type SiteConfig } from "./api";
import { useTheme } from "./theme";
import { useToast } from "./toast";

interface AuthState {
  me: Me | undefined;
  config: SiteConfig | undefined;
  loading: boolean;
  signOut: () => void;
  setMe: (me: Me) => void;
}

/** Queries holding one user's data: dropped on sign-out so the next person never sees them. */
const PRIVATE_KEYS = new Set(["alerts", "workspace", "workspaces", "members", "invites", "api-keys", "pipeline", "pipeline-summary", "subscription", "copilot", "recommendations"]);

const AuthContext = createContext<AuthState>({
  me: undefined,
  config: undefined,
  loading: true,
  signOut: () => {},
  setMe: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000 });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: (m) => {
      qc.setQueryData(["me"], m);
      qc.removeQueries({ predicate: (q) => PRIVATE_KEYS.has(String(q.queryKey[0])) });
      toast("success", "Signed out");
    },
  });
  return (
    <AuthContext.Provider
      value={{
        me: me.data,
        config: config.data,
        loading: me.isLoading,
        signOut: () => logout.mutate(),
        setMe: (m) => qc.setQueryData(["me"], m),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (o: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string }) => void;
          renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
        };
      };
    };
  }
}

let gsiPromise: Promise<void> | null = null;
function loadGsi(): Promise<void> {
  gsiPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      gsiPromise = null;
      reject(new Error("could not load Google sign-in"));
    };
    document.head.appendChild(s);
  });
  return gsiPromise;
}

/** Google's own "Sign in with Google" button. Google verifies the person; our server
 *  verifies Google's signed token and starts a session. */
export function GoogleButton({ onDone }: { onDone?: () => void }) {
  const { config, setMe } = useAuth();
  const { dark } = useTheme();
  const toast = useToast();
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const clientId = config?.google_client_id;
  // Latest callbacks in a ref, so Google's button is set up once per client id/theme
  // rather than on every render.
  const handlers = useRef({ setMe, toast, onDone });
  handlers.current = { setMe, toast, onDone };

  useEffect(() => {
    if (!clientId || !ref.current) return;
    let cancelled = false;
    loadGsi()
      .then(() => {
        if (cancelled || !ref.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: async ({ credential }) => {
            const h = handlers.current;
            try {
              h.setMe(await api.googleLogin(credential));
              h.toast("success", "Signed in");
              h.onDone?.();
            } catch (e) {
              h.toast("error", e instanceof ApiError ? e.message : "Sign-in failed");
            }
          },
        });
        ref.current.innerHTML = "";
        window.google.accounts.id.renderButton(ref.current, {
          theme: dark ? "filled_black" : "outline",
          size: "large",
          shape: "rectangular",
          text: "continue_with",
          logo_alignment: "left",
        });
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [clientId, dark]);

  if (!config) return <div className="skeleton h-10 w-56 rounded-md" />;
  if (!clientId) {
    return config.dev_login ? (
      <DevLogin onDone={onDone} />
    ) : (
      <p className="text-sm text-ink-3">Google sign-in isn't configured on this server yet (GOOGLE_CLIENT_ID).</p>
    );
  }
  return (
    <div>
      <div ref={ref} className="min-h-10" />
      {failed && <p className="mt-2 text-sm text-critical">Couldn't reach Google. Check your connection and reload.</p>}
    </div>
  );
}

/** Local development only (the server refuses it unless DEBUG and DEV_LOGIN_ENABLED). */
function DevLogin({ onDone }: { onDone?: () => void }) {
  const { setMe } = useAuth();
  const toast = useToast();
  const [email, setEmail] = useState("");
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          setMe(await api.devLogin(email, email.split("@")[0]));
          toast("success", "Signed in (development login)");
          onDone?.();
        } catch (err) {
          toast("error", err instanceof ApiError ? err.message : "Sign-in failed");
        }
      }}
    >
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        aria-label="Email for development sign-in"
        className={cx(inputClass, "min-w-0 flex-1 basis-48")}
      />
      <Button variant="primary">Dev sign-in</Button>
      <span className="w-full text-xs text-ink-3">
        <span className="label mr-1.5 text-signal-text">Dev</span>Local development login. Google sign-in replaces this once GOOGLE_CLIENT_ID is set.
      </span>
    </form>
  );
}
