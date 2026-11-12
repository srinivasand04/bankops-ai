import type { Priority } from "./incident";

export type CalendarPeriodType =
  | "MONTH_END_CLOSE" | "QUARTER_END_CLOSE" | "YEAR_END_CLOSE" | "PAYROLL"
  | "REGULATORY_DEADLINE" | "PEAK_PERIOD" | "BANK_HOLIDAY";

export const PERIOD_TYPES: CalendarPeriodType[] = [
  "MONTH_END_CLOSE", "QUARTER_END_CLOSE", "YEAR_END_CLOSE", "PAYROLL", "REGULATORY_DEADLINE", "PEAK_PERIOD", "BANK_HOLIDAY",
];

export interface CalendarPeriod {
  id: number;
  name: string;
  period_type: CalendarPeriodType;
  starts_at: string;
  /** Exclusive: the period ends just before this moment. */
  ends_at: string;
  /** Empty = every application. */
  application_codes: string[];
  raises_priority: boolean;
  description: string | null;
  data_source: string;
  created_by: string;
}

export interface CalendarPeriodInput {
  name: string;
  period_type: CalendarPeriodType;
  starts_at: string;
  ends_at: string;
  application_codes: string[];
  raises_priority?: boolean;
  description?: string | null;
}

export interface ActiveCalendar {
  application_code: string;
  at: string;
  periods: CalendarPeriod[];
  priority_preview: { priority: Priority; reason: string } | null;
}
