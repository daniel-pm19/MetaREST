import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { AuthProvider, useAuth } from "./auth";
import { StoreProvider, useStore } from "./store";
import { Layout, navItems, type Route } from "./components/Layout";
import { ErrorState } from "./components/ui";
import { Dashboard } from "./pages/Dashboard";
import { Review } from "./pages/Review";
import { Discarded } from "./pages/Discarded";
import { HistoryPage } from "./pages/History";
import { Compare } from "./pages/Compare";
import { Projects } from "./pages/Projects";
import { Admin } from "./pages/Admin";
import { Login } from "./pages/Login";

const parse = (): Route => {
  const h = window.location.hash.replace("#/", "") as Route;
  return navItems.some((i) => i.id === h) ? h : "resumen";
};

const Spinner = ({ text }: { text: string }) => (
  <div className="grid h-full place-items-center text-slate-500">
    <div className="flex items-center gap-2"><Loader2 className="size-5 animate-spin" aria-hidden /> {text}</div>
  </div>
);

function Shell() {
  const [route, setRoute] = useState<Route>(parse);
  const { loaded, loadError, reload } = useStore();
  const { can } = useAuth();
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  // Una ruta a la que el rol no tiene acceso cae en el resumen (el backend también lo bloquea).
  const allowed = navItems.find((i) => i.id === route)?.allowed(can) ?? false;
  const current: Route = allowed ? route : "resumen";

  let page;
  if (!loaded) page = <Spinner text="Cargando análisis…" />;
  else if (loadError && current !== "proyectos") page = <ErrorState message={loadError} onRetry={reload} />;
  else {
    page = { resumen: <Dashboard />, revision: <Review />, descartadas: <Discarded />, decisiones: <HistoryPage />, comparar: <Compare />, proyectos: <Projects />, admin: <Admin /> }[current];
  }
  return <Layout route={current}>{page}</Layout>;
}

function Gate() {
  const { status } = useAuth();
  if (status === "loading") return <Spinner text="Verificando sesión…" />;
  if (status === "out") return <Login />;
  return <StoreProvider><Shell /></StoreProvider>;
}

export default function App() {
  return <AuthProvider><Gate /></AuthProvider>;
}
