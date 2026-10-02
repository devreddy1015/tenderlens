import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Compass } from "lucide-react";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { EmptyState, Skeleton } from "./components/ui";
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
const Private = lazy(() => import("./pages/Private"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false, retry: 1 } },
});

function NotFound() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-20">
      <EmptyState icon={<Compass className="size-6" />} title="Page not found">
        <Link to="/" className="text-brand hover:underline">
          Back to the home page
        </Link>
      </EmptyState>
    </div>
  );
}

const fallback = (
  <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
    <Skeleton className="mb-4 h-9 w-64" />
    <Skeleton className="h-96 w-full rounded-2xl" />
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
                    <Route path="private" element={<Private />} />
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
