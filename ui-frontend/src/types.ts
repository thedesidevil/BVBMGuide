export interface CityNode {
  name: string;
  status: "pending" | "in_progress" | "reviewed";
  restaurant_count: number;
}

export interface CountryNode {
  cities: CityNode[];
  status: "pending" | "in_progress" | "reviewed";
}

export type TreeData = Record<string, CountryNode>;

export interface Restaurant {
  name: string;
  city?: string;
  cuisine_type?: string[];
  hours?: string;
  price_range?: string;
  area?: string;
  ambience?: string;
  nearby_landmarks?: string[];
  must_try_dishes?: string[];
  best_for?: string[];
  vegetarian_friendly?: boolean;
  pure_vegetarian?: boolean;
  highlights?: string[];
  source_files?: string[];
}

export interface Attraction {
  name: string;
  city?: string;
  description?: string;
  hours?: string;
  entry_fee?: string;
  recommended_duration?: string;
  source_files?: string[];
}

export interface CityData {
  restaurants: Restaurant[];
  attractions: Attraction[];
  hotels: any[];
  local_dishes: any[];
  phrases: any[];
  safety_tips: any[];
  souvenirs: any[];
  emergency_contacts: any[];
  connectivity_tips: any[];
  transport_options: any[];
  health_tips: any[];
  source_files: string[];
}

export interface SweepItem {
  city: string;
  index: number;
  item: Record<string, any>;
}

export interface SweepResult {
  category: string;
  field: string | null;
  filter: string | null;
  total: number;
  items: SweepItem[];
}

export interface AuditEntry {
  action: "edit" | "delete" | "add";
  category: string;
  city: string;
  item_name: string;
  changes?: { field: string; old: any; new: any }[];
  reason?: string;
  item_snapshot?: Record<string, any>;
  changed_by: string;
  changed_at: string;
}

// --- Ingest types ---

export interface IngestFile {
  id: string;
  filename: string;
  size: number;
  type: "pdf" | "docx";
  state: "uploaded" | "classified" | "extracted" | "excluded" | "persisted" | "failed";
  assigned_folder: string | null;
  is_new_folder: boolean;
  excluded: boolean;
  error?: string;
  data?: Record<string, any>;
}

export interface IngestSession {
  session_id: string;
  files: IngestFile[];
}

export interface PersistResult {
  persisted_files: number;
  affected_cities: string[];
}

// --- Verify types ---

export interface VerifyFinding {
  check_id: string;
  layer: "rule" | "ai";
  severity: "RED" | "YELLOW";
  section: string;
  description: string;
  evidence: string;
}

export interface VerifyNarratives {
  overall: string;
  days: string;
  restaurants: string;
  static_sections: string;
}

export interface VerifyMeta {
  red_count: number;
  yellow_count: number;
  passed_count: number;
  model: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  cost_usd?: number | null;
}

export interface VerifyResult {
  findings: VerifyFinding[];
  narratives: VerifyNarratives;
  meta: VerifyMeta;
}

// --- Hotel Options types ---

export interface HotelOptionsHotel {
  name: string;
  category: string;
  room_type: string;
  cancellation: string;
  meal_type: string;
  dates: string;
}

export interface HotelOptionsPricing {
  total_online_price: number;
  customer_discount: number;
  discounted_price: number;
  discount_pct: number;
}

export interface HotelOptionsPlan {
  label: string;
  hotels: HotelOptionsHotel[];
  pricing: HotelOptionsPricing;
}

export interface HotelOptionsUnknownCode {
  code: string;
  hotel_name: string;
  plan_label: string;
}

export interface HotelOptionsNotFound {
  sheet_name: string;
  plan_label: string;
}

export interface HotelOptionsParseResult {
  client_name: string;
  destination: string;
  requirements: string;
  plans: HotelOptionsPlan[];
  unknown_codes: HotelOptionsUnknownCode[];
  not_found: HotelOptionsNotFound[];
  maps_api_calls: number;
}
