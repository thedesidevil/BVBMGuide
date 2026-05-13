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

  // --- Ingest ---
  ingestUpload: async (files: File[]): Promise<{ session_id: string; files: any[] }> => {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const res = await fetch(`${BASE}/ingest/upload`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
    return res.json();
  },
  ingestUploadMore: async (sessionId: string, files: File[]): Promise<{ session_id: string; files: any[] }> => {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }
    const res = await fetch(`${BASE}/ingest/${sessionId}/upload`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
    return res.json();
  },
  ingestDeleteFile: (sessionId: string, fileId: string) =>
    request<{ status: string; files: any[] }>(`/ingest/${sessionId}/files/${fileId}`, { method: "DELETE" }),
  ingestUpdateFile: (sessionId: string, fileId: string, updates: { assigned_folder?: string; excluded?: boolean }) =>
    request<any>(`/ingest/${sessionId}/files/${fileId}`, { method: "PUT", body: JSON.stringify(updates) }),
  ingestClassify: (sessionId: string) =>
    request<{ files: any[] }>(`/ingest/${sessionId}/classify`, { method: "POST" }),
  ingestExtract: (sessionId: string) =>
    request<{ status: string }>(`/ingest/${sessionId}/extract`, { method: "POST" }),
  ingestStatus: (sessionId: string) =>
    request<{ files: any[] }>(`/ingest/${sessionId}/extract/status`),
  ingestSaveData: (sessionId: string, fileId: string, data: any) =>
    request(`/ingest/${sessionId}/files/${fileId}/data`, { method: "PUT", body: JSON.stringify(data) }),
  ingestPersist: (sessionId: string) =>
    request<{ persisted_files: number; affected_cities: string[] }>(`/ingest/${sessionId}/persist`, { method: "POST" }),
  ingestFolders: () =>
    request<{ folders: string[] }>("/ingest/folders"),
  ingestHistory: () =>
    request<{ files: { filename: string; destination: string; covered_cities: string[]; ingested_at: string }[] }>("/ingest/history"),
};
