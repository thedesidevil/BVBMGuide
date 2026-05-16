import { useEffect, useState } from "react";
import { Layout } from "./components/Layout";
import { LoadingScreen } from "./components/LoadingScreen";
import { Sidebar } from "./components/Sidebar";
import { CityView } from "./components/CityView";
import { CountryView } from "./components/CountryView";
import { SweepMode } from "./components/SweepMode";
import { IngestWizard } from "./components/IngestWizard";
import { IngestHistory } from "./components/IngestHistory";
import { AuditLog } from "./components/AuditLog";
import type { TreeData } from "./types";
import { api } from "./api/client";

export default function App() {
  const [mode, setMode] = useState<"city" | "sweep" | "ingest" | "history" | "audit">("city");
  const [tree, setTree] = useState<TreeData>({});
  const [treeLoaded, setTreeLoaded] = useState(false);
  const [selectedCity, setSelectedCity] = useState<string | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/me", { credentials: "same-origin" })
      .then((r) => {
        if (r.ok) return r.json();
        return null;
      })
      .then((data) => {
        if (data?.email) setUserEmail(data.email);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    api.getTree().then((data) => {
      setTree(data as TreeData);
      setTreeLoaded(true);
    });
  }, []);

  const reviewedCount = Object.values(tree).reduce(
    (sum, n) => sum + n.cities.filter((c) => c.status === "reviewed").length, 0
  );
  const totalCount = Object.values(tree).reduce((sum, n) => sum + n.cities.length, 0);

  return (
    <>
      <LoadingScreen loaded={treeLoaded} />
      <Layout
        mode={mode}
        onModeChange={setMode}
        reviewedCount={reviewedCount}
        totalCount={totalCount}
        userEmail={userEmail}
        sidebar={
          <Sidebar
            tree={tree}
            selectedCity={selectedCity}
            selectedCountry={selectedCountry}
            onSelectCity={(city) => { setSelectedCity(city); setSelectedCountry(null); }}
            onSelectCountry={(country) => { setSelectedCountry(country); setSelectedCity(null); }}
          />
        }
      >
        {mode === "city" && selectedCity && (
          <CityView cityName={selectedCity} onRefreshTree={() => api.getTree().then((data) => setTree(data as TreeData))} userEmail={userEmail} />
        )}
        {mode === "city" && selectedCountry && (
          <CountryView countryName={selectedCountry} onRefreshTree={() => api.getTree().then((data) => setTree(data as TreeData))} />
        )}
        {mode === "city" && !selectedCity && !selectedCountry && (
          <div className="text-slate-400 text-center py-20">Select a city or country from the sidebar</div>
        )}
        {mode === "sweep" && <SweepMode />}
        {mode === "ingest" && <IngestWizard onDone={() => { setMode("city"); api.getTree().then((data) => setTree(data as TreeData)); }} />}
        {mode === "history" && <IngestHistory />}
        {mode === "audit" && <AuditLog />}
      </Layout>
    </>
  );
}
