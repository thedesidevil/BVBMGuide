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
  action: string;
  category: string;
  city: string;
  item_name: string;
  reason: string;
  deleted_by: string;
  deleted_at: string;
  item_snapshot: Record<string, any>;
}
