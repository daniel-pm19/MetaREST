import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { StoreProvider, useStore } from "./store";
import { Layout, type Route } from "./components/Layout";
import { ErrorState } from "./components/ui";
import { Dashboard } from "./pages/Dashboard";
import { Review } from "./pages/Review";
import { Discarded } from "./pages/Discarded";
import { HistoryPage } from "./pages/History";

const routes: Route[] = ["resumen", "revision", "descartadas", "decisiones"];
const parse = (): Route => {
  const h = window.location.hash.replace("#/", "") as Route;
  return routes.includes(h) ? h : "resumen";
};

function Shell() {
  const [route, setRoute] = useState<Route>(parse);
  const { run, loadError, reload } = useStore();
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  let page;
  if (!run) {
    page = loadError ? (
      <ErrorState message={loadError} onRetry={reload} />
    ) : (
      <div className="grid h-full place-items-center text-slate-500">
        <div className="flex items-center gap-2"><Loader2 className="size-5 animate-spin" aria-hidden /> Cargando análisis…</div>
      </div>
    );
  } else {
    page = route === "revision" ? <Review /> : route === "descartadas" ? <Discarded /> : route === "decisiones" ? <HistoryPage /> : <Dashboard />;
  }
  return <Layout route={route}>{page}</Layout>;
}

export default function App() {
  return <StoreProvider><Shell /></StoreProvider>;
}
