import { useEffect, useState } from "react";
import { Layout } from "./components/Layout";
import { Sidebar } from "./components/Sidebar";
import { CityView } from "./components/CityView";
import { TreeData } from "./types";
import { api } from "./api/client";

export default function App() {
  const [mode, setMode] = useState<"city" | "sweep">("city");
  const [tree, setTree] = useState<TreeData>({});
  const [selectedCity, setSelectedCity] = useState<string | null>(null);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);

  useEffect(() => {
    api.getTree().then((data) => setTree(data as TreeData));
  }, []);

  const reviewedCount = Object.values(tree).reduce(
    (sum, n) => sum + n.cities.filter((c) => c.status === "reviewed").length, 0
  );
  const totalCount = Object.values(tree).reduce((sum, n) => sum + n.cities.length, 0);

  return (
    <Layout
      mode={mode}
      onModeChange={setMode}
      reviewedCount={reviewedCount}
      totalCount={totalCount}
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
      {mode === "city" && selectedCity && <CityView cityName={selectedCity} onRefreshTree={() => api.getTree().then((data) => setTree(data as TreeData))} />}
      {mode === "city" && selectedCountry && <div className="text-slate-400 text-center py-20">Country view for <strong>{selectedCountry}</strong> — next task</div>}
      {mode === "city" && !selectedCity && !selectedCountry && <div className="text-slate-400 text-center py-20">Select a city or country from the sidebar</div>}
      {mode === "sweep" && <div className="text-slate-400 text-center py-20">Sweep mode — next task</div>}
    </Layout>
  );
}
