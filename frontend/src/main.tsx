import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Compass } from "lucide-react";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { EmptyState, Skeleton } from "./components/ui";
import { ApiError } from "./lib/api";
import { AuthProvider } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import { ToastProvider } from "./lib/toast";
import Home from "./pages/Home";
import "./index.css";

// Code-split everything but the home page.
const Explore = lazy(() => import("./pages/Explore"));
const TenderPage = lazy(() => import("./pages/TenderPage"));
const MapPage = lazy(() => import("./pages/MapPage"));
const SectorsPage = lazy(() => import("./pages/SectorsPage"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Pricing = lazy(() => import("./pages/Pricing"));
const Pipeline = lazy(() => import("./pages/Pipeline"));
const Copilot = lazy(() => import("./pages/Copilot"));
const WorkspacePage = lazy(() => import("./pages/Workspace"));
const Coverage = lazy(() => import("./pages/Coverage"));
const Invite = lazy(() => import("./pages/Invite"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // A 4xx (signed out, over quota, not found) won't change on a retry; a network blip may.
      retry: (failures, e) => failures < 1 && !(e instanceof ApiError && e.status >= 400 && e.status < 500),
    },
  },
});

function NotFound() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-24">
      <EmptyState icon={<Compass className="size-5" />} title="Nothing at this address">
        <p className="num mb-4 text-xs text-ink-3">HTTP 404 · {window.location.pathname}</p>
        <Link to="/" className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal">
          Back to the home page
        </Link>
      </EmptyState>
    </div>
  );
}

const fallback = (
  <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
    <Skeleton className="mb-3 h-3 w-28" />
    <Skeleton className="mb-8 h-9 w-72" />
    <Skeleton className="h-96 w-full rounded-lg" />
  </div>
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>
            <BrowserRouter>
              <Suspense fallback={fallback}>
                <Routes>
                  <Route element={<Layout />}>
                    <Route index element={<Home />} />
                    <Route path="tenders" element={<Explore />} />
                    <Route path="tenders/:id" element={<TenderPage />} />
                    <Route path="map" element={<MapPage />} />
                    <Route path="sectors" element={<SectorsPage />} />
                    <Route path="alerts" element={<Alerts />} />
                    <Route path="pipeline" element={<Pipeline />} />
                    <Route path="copilot" element={<Copilot />} />
                    <Route path="pricing" element={<Pricing />} />
                    <Route path="workspace" element={<WorkspacePage />} />
                    <Route path="coverage" element={<Coverage />} />
                    <Route path="invite/:token" element={<Invite />} />
                    {/* The private-tenders waitlist is gone; old links land on the plans. */}
                    <Route path="private" element={<Navigate to="/pricing" replace />} />
                    <Route path="*" element={<NotFound />} />
                  </Route>
                </Routes>
              </Suspense>
            </BrowserRouter>
          </AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
