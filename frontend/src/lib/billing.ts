import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, api, errorMessage, type Interval, type Plan, quotaExceeded, type Subscription } from "./api";
import { useAuth } from "./auth";
import { useSignedIn } from "./queries";
import { useToast } from "./toast";

export const RAZORPAY_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

interface RazorpayOptions {
  key: string;
  subscription_id: string;
  name: string;
  description: string;
  prefill?: { name?: string; email?: string };
  theme?: { color?: string };
  handler: (r: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) => void;
  modal?: { ondismiss?: () => void };
}

declare global {
  interface Window {
    Razorpay?: new (o: RazorpayOptions) => { open: () => void; on: (event: string, cb: (r: unknown) => void) => void };
  }
}

let scriptPromise: Promise<void> | null = null;

/** Razorpay's own Checkout script, loaded the first time someone pays. Card and UPI details
 *  go to Razorpay's iframe; they never touch our page or our server. */
export function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  scriptPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = RAZORPAY_SCRIPT;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      scriptPromise = null;
      reject(new Error("Couldn't load Razorpay. Check your connection and try again."));
    };
    document.head.appendChild(s);
  });
  return scriptPromise;
}

/** Opens Razorpay Checkout for a subscription. Resolves true once the payment is authorised,
 *  false if the person closes the window. */
function payWithRazorpay(o: { keyId: string; subscriptionId: string; plan: Plan; email?: string; name?: string }): Promise<boolean> {
  return new Promise((resolve, reject) => {
    if (!window.Razorpay) return reject(new Error("Razorpay is not available."));
    const signal = getComputedStyle(document.documentElement).getPropertyValue("--signal").trim();
    const rzp = new window.Razorpay({
      key: o.keyId,
      subscription_id: o.subscriptionId,
      name: "TenderLens",
      description: `${o.plan.name} plan`,
      prefill: { email: o.email, name: o.name },
      theme: { color: signal || "#e8920c" },
      handler: () => resolve(true),
      modal: { ondismiss: () => resolve(false) },
    });
    rzp.on("payment.failed", () => reject(new Error("The payment didn't go through. No money was taken; try again or use another method.")));
    rzp.open();
  });
}

export const ACTIVATION_TIMEOUT_MS = 120_000;
const POLL_MS = 3000;

type Outcome = "activated" | "paid" | "redirected" | "dismissed";

/** Buying a plan. With the fake provider (development) the plan is active at once. With
 *  Razorpay the browser opens Razorpay Checkout (key_id + subscription_id); if the script
 *  can't load, Razorpay's hosted page (short_url) opens instead. Either way the plan turns
 *  on when Razorpay's webhook reaches our server, so the subscription is polled until it is
 *  active on the new plan, for up to two minutes. */
export function useCheckout() {
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const signedIn = useSignedIn();
  const [awaiting, setAwaiting] = useState<string | null>(null);
  const live = (d: Subscription | undefined, code: string) => d?.plan === code && d.status === "active";

  const sub = useQuery({
    queryKey: ["subscription"],
    queryFn: api.billing.subscription,
    enabled: signedIn,
    refetchInterval: (q) => (awaiting && !live(q.state.data, awaiting) ? POLL_MS : false),
  });
  const arrived = awaiting !== null && live(sub.data, awaiting);
  useEffect(() => {
    if (!awaiting) return;
    if (arrived) {
      setAwaiting(null);
      qc.invalidateQueries({ queryKey: ["workspace"] });
      toast("success", "Your new plan is active.");
      return;
    }
    const t = setTimeout(() => {
      setAwaiting(null);
      toast("success", "Razorpay is still confirming the payment. Your plan switches as soon as it does; refresh in a minute.");
    }, ACTIVATION_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [awaiting, arrived, qc, toast]);

  const checkout = useMutation({
    mutationFn: async ({ plan, interval }: { plan: Plan; interval: Interval }): Promise<{ plan: Plan; done: Outcome }> => {
      const r = await api.billing.checkout(plan.code, interval);
      if (r.provider === "fake") return { plan, done: "activated" };
      try {
        await loadRazorpay();
      } catch (e) {
        if (!r.short_url) throw e;
        // Razorpay's hosted payment page does the same job in a new tab.
        window.open(r.short_url, "_blank", "noopener");
        return { plan, done: "redirected" };
      }
      const paid = await payWithRazorpay({ keyId: r.key_id, subscriptionId: r.subscription_id, plan, email: me?.user?.email, name: me?.user?.name });
      return { plan, done: paid ? "paid" : "dismissed" };
    },
    onSuccess: ({ plan, done }) => {
      if (done === "activated") {
        toast("success", `You're on the ${plan.name} plan.`);
        qc.invalidateQueries({ queryKey: ["subscription"] });
        qc.invalidateQueries({ queryKey: ["workspace"] });
      } else if (done === "paid" || done === "redirected") {
        toast("success", done === "paid" ? `Payment received. Switching you to ${plan.name}…` : "Complete the payment in the Razorpay tab. This page updates once it's confirmed.");
        setAwaiting(plan.code);
        qc.invalidateQueries({ queryKey: ["subscription"] });
      }
    },
    onError: (e) => {
      if (quotaExceeded(e)) return; // the upgrade dialog opens (lib/queryClient.ts)
      toast("error", e instanceof ApiError ? errorMessage(e, "Couldn't start the checkout") : e instanceof Error ? e.message : "Couldn't start the checkout");
    },
  });

  return { checkout, awaiting };
}
