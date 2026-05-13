import { useState, useMemo } from "react";
import { TreeData } from "../types";

interface SidebarProps {
  tree: TreeData;
  selectedCity: string | null;
  selectedCountry: string | null;
  onSelectCity: (city: string) => void;
  onSelectCountry: (country: string) => void;
}

const STATUS_COLORS = {
  reviewed: "bg-green-500",
  in_progress: "bg-amber-400",
  pending: "bg-slate-300",
};

export function Sidebar({ tree, selectedCity, selectedCountry, onSelectCity, onSelectCountry }: SidebarProps) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set(Object.keys(tree)));

  const filteredTree = useMemo(() => {
    if (!search.trim()) return tree;
    const q = search.toLowerCase();
    const result: TreeData = {};
    for (const [country, node] of Object.entries(tree)) {
      if (country.toLowerCase().includes(q)) {
        result[country] = node;
      } else {
        const matchedCities = node.cities.filter((c) => c.name.toLowerCase().includes(q));
        if (matchedCities.length > 0) {
          result[country] = { ...node, cities: matchedCities };
        }
      }
    }
    return result;
  }, [tree, search]);

  const toggleExpand = (country: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(country)) next.delete(country);
      else next.add(country);
      return next;
    });
  };

  const totalCities = Object.values(tree).reduce((sum, n) => sum + n.cities.length, 0);
  const totalRestaurants = Object.values(tree).reduce(
    (sum, n) => sum + n.cities.reduce((s, c) => s + c.restaurant_count, 0), 0
  );

  return (
    <div className="py-4">
      <div className="px-4 pb-4 text-xs text-slate-500 border-b border-slate-200 mb-3">
        <div className="mb-1"><strong>{Object.keys(tree).length}</strong> countries · <strong>{totalCities}</strong> cities · <strong>{totalRestaurants}</strong> restaurants</div>
      </div>
      <div className="px-3 mb-3">
        <input
          type="text"
          placeholder="Search countries or cities..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-3 py-2 text-sm border border-slate-200 rounded-md bg-slate-50 focus:outline-none focus:border-blue-400"
        />
      </div>
      {Object.entries(filteredTree).map(([country, node]) => (
        <div key={country} className="mb-1">
          <button
            onClick={() => { toggleExpand(country); onSelectCountry(country); }}
            className={`w-full px-4 py-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wide cursor-pointer transition-colors ${
              selectedCountry === country ? "bg-amber-50 text-amber-800 border-r-[3px] border-amber-400" : "text-slate-500 hover:bg-slate-50"
            }`}
          >
            <span className={`text-[10px] transition-transform ${expanded.has(country) ? "rotate-90" : ""}`}>▶</span>
            {country}
            <span className="ml-auto text-[10px] font-medium bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">
              {node.cities.length}
            </span>
          </button>
          {expanded.has(country) && (
            <div>
              {node.cities.map((city) => (
                <button
                  key={city.name}
                  onClick={() => onSelectCity(city.name)}
                  className={`w-full pl-9 pr-4 py-[7px] flex items-center gap-2.5 text-[13px] cursor-pointer transition-colors ${
                    selectedCity === city.name ? "bg-blue-50 text-blue-600 font-medium border-r-[3px] border-blue-500" : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className={`w-2 h-2 rounded-full ${STATUS_COLORS[city.status]}`} />
                  {city.name}
                  <span className="ml-auto text-[11px] text-slate-400">{city.restaurant_count}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
