const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export const api = {
  getTree: () => request<Record<string, any>>("/tree"),
  getCity: (name: string) => request<Record<string, any>>(`/city/${encodeURIComponent(name)}`),
  saveCity: (name: string, data: any) =>
    request(`/city/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteItem: (city: string, category: string, index: number, reason: string, deletedBy: string) =>
    request(`/city/${encodeURIComponent(city)}/${category}/${index}`, {
      method: "DELETE",
      body: JSON.stringify({ reason, deleted_by: deletedBy }),
    }),
  getCountry: (name: string) => request<Record<string, any>>(`/country/${encodeURIComponent(name)}`),
  saveCountry: (name: string, data: any) =>
    request(`/country/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(data) }),
  reviewCity: (name: string, reviewedBy: string) =>
    request(`/city/${encodeURIComponent(name)}/review`, {
      method: "POST",
      body: JSON.stringify({ reviewed_by: reviewedBy }),
    }),
  reviewCountry: (name: string, reviewedBy: string) =>
    request(`/country/${encodeURIComponent(name)}/review`, {
      method: "POST",
      body: JSON.stringify({ reviewed_by: reviewedBy }),
    }),
  getSweep: (category: string, field?: string, filter?: string) => {
    const params = new URLSearchParams({ category });
    if (field) params.set("field", field);
    if (filter) params.set("filter", filter);
    return request<Record<string, any>>(`/sweep?${params}`);
  },
  saveSweep: (edits: any[]) =>
    request("/sweep", { method: "PUT", body: JSON.stringify({ edits }) }),
  getAudit: (limit?: number) =>
    request<any[]>(`/audit${limit ? `?limit=${limit}` : ""}`),
  logDeletion: (city: string, category: string, itemName: string, reason: string, itemSnapshot: any, deletedBy: string) =>
    request("/audit", {
      method: "POST",
      body: JSON.stringify({ city, category, item_name: itemName, reason, item_snapshot: itemSnapshot, deleted_by: deletedBy }),
    }),
};
