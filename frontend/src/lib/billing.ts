import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, errorMessage, type Interval, type Plan } from "./api";
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

/** Buying a plan. With the fake provider (development) the plan is active at once; with
 *  Razorpay the plan turns on when Razorpay's webhook reaches our server, so the
 *  subscription is polled for a minute after a successful payment. */
export function useCheckout() {
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const signedIn = useSignedIn();
  const [awaiting, setAwaiting] = useState<string | null>(null);

  // Poll while a paid plan is on its way; stop when it arrives or after a minute.
  const sub = useQuery({
    queryKey: ["subscription"],
    queryFn: api.billing.subscription,
    enabled: signedIn,
    refetchInterval: (q) => (awaiting && q.state.data?.plan !== awaiting ? 3000 : false),
  });
  useEffect(() => {
    if (!awaiting) return;
    if (sub.data?.plan === awaiting) {
      setAwaiting(null);
      qc.invalidateQueries({ queryKey: ["workspace"] });
      toast("success", "Your new plan is active.");
      return;
    }
    const t = setTimeout(() => setAwaiting(null), 60_000);
    return () => clearTimeout(t);
  }, [awaiting, sub.data?.plan, qc, toast]);

  const checkout = useMutation({
    mutationFn: async ({ plan, interval }: { plan: Plan; interval: Interval }) => {
      const r = await api.billing.checkout(plan.code, interval);
      if (r.provider === "fake") return { plan, done: "activated" as const };
      await loadRazorpay();
      const paid = await payWithRazorpay({ keyId: r.key_id, subscriptionId: r.subscription_id, plan, email: me?.user?.email, name: me?.user?.name });
      return { plan, done: paid ? ("paid" as const) : ("dismissed" as const) };
    },
    onSuccess: ({ plan, done }) => {
      if (done === "activated") {
        toast("success", `You're on the ${plan.name} plan.`);
        qc.invalidateQueries({ queryKey: ["subscription"] });
        qc.invalidateQueries({ queryKey: ["workspace"] });
      } else if (done === "paid") {
        toast("success", `Payment received. Switching you to ${plan.name}…`);
        setAwaiting(plan.code);
        qc.invalidateQueries({ queryKey: ["subscription"] });
      }
    },
    onError: (e) => toast("error", e instanceof Error && !("status" in e) ? e.message : errorMessage(e, "Couldn't start the checkout")),
  });

  return { checkout, awaiting };
}
