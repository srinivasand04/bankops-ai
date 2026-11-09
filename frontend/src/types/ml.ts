export interface MlRun {
  id: number;
  task: string;
  algorithm: string;
  version: string;
  is_active: boolean;
  params: Record<string, unknown>;
  metrics: Record<string, number | null>;
  details?: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- per-task shapes
  n_train: number;
  n_test: number;
  train_from: string | null;
  train_to: string | null;
  test_from: string | null;
  test_to: string | null;
  trained_by: string;
  created_at: string;
}

export interface MlTask {
  task: string;
  description: string;
  active: MlRun | null;
  status: { state: string; reason?: string; seconds?: number; active?: string } | null;
}

export interface MlPrediction {
  id: number;
  evidence_id: string;
  task: string;
  algorithm: string;
  version: string;
  prediction: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  explanation: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  created_at: string;
}

export interface ScoredChange extends MlPrediction {
  reference: string;
  application: string;
  title: string;
  risk_level: string;
  change_type: string;
  status: string;
  deployed_at: string;
}
