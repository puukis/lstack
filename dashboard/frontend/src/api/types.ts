export interface HookEntry {
  exists: boolean;
  syntax?: "pass" | "warn" | "fail" | "unknown";
}

export interface HooksSection {
  session_start?: HookEntry;
  pre_tool?: HookEntry;
  post_tool?: HookEntry;
  pre_compact?: HookEntry;
  stop?: HookEntry;
  statusline?: { exists: boolean };
}

export interface SkillsSection { count: number; items: string[] }
export interface AgentsSection { count: number; items: string[] }

export interface MemorySection {
  db_reachable: boolean;
  observations_count: number;
  learnings_count: number;
  fts_available: boolean;
  semantic_available: boolean;
}

export interface ObservationItem {
  id: number;
  session_id: string;
  project: string;
  scope: "project" | "global" | "other";
  content: string;
  tags: string[];
  created_at: string;
}

export interface LearningItem {
  id: number;
  session_id: string;
  project: string;
  scope: "project" | "global" | "other";
  key: string;
  type: string;
  insight: string;
  confidence: number;
  source: string;
  trusted: boolean;
  tags: string[];
  files: string[];
  branch: string | null;
  commit_sha: string | null;
  supersedes_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryDetail extends MemorySection {
  available: boolean;
  error?: string;
  observations: ObservationItem[];
  learnings: LearningItem[];
  limit: number;
}

export interface RuntimeSection {
  os: string;
  shell_mode: string;
  python_available: boolean;
  python_provider: string;
  python_version?: string;
  git_available: boolean;
  path_rule: string;
}

export interface InstallSection {
  claude_dir: string;
  settings_exists: boolean;
  settings_valid_json: boolean;
  version: string;
}

export interface ProjectSection {
  name: string;
  root_path_display: string;
  git_branch: string;
}

export interface HealthSection {
  available: boolean;
  latest_saved: string | null;
  note: string;
}

export interface Worktree {
  name: string;
  branch: string;
  status: "running" | "done" | "failed" | "unknown";
}

export interface ParallelSection {
  available: boolean;
  legacy_command: string;
  active: number;
  done: number;
  failed: number;
  worktrees: Worktree[];
}

export type DoctorStatus = "pass" | "warn" | "fail" | "unknown";

export interface DoctorSection {
  status: DoctorStatus;
  warnings: string[];
  failures: string[];
  available?: boolean;
  error?: string;
}

export interface ActionItem {
  id: string;
  label: string;
  category: string;
  description?: string;
  enabled: boolean;
  danger: "low" | "medium" | "high";
  requires_confirmation: boolean;
  requires_receipt: boolean;
  requires_firewall_check: boolean;
  requires_audit_log: boolean;
  v1_behavior: string;
}

export interface ActionsSection {
  interactive_ready: boolean;
  enabled: boolean;
  mode: string;
  items: ActionItem[];
  v2_rules?: string[];
}

export interface LBrainSection {
  available?: boolean;
  error?: string;
  passport?: { available: boolean; stack?: string[]; package_manager?: string };
  firewall?: { available: boolean; status: string; warning_count: number };
  receipts?: { open: { id: number; title: string; status: string } | null; recent: unknown[] };
  contracts?: { active: unknown; active_count: number };
  decisions?: { active_count: number; top: unknown[] };
  failed_attempts?: { count: number };
  capture?: { events_count: number; pending_candidates_count: number; promoted_candidates_count: number };
  context_governor?: { count?: number; items?: unknown[] };
  doctor?: DoctorSection;
}

export interface Overview {
  schema_version: number;
  generated_at: string;
  read_only: boolean;
  project: ProjectSection;
  runtime: RuntimeSection;
  install: InstallSection;
  hooks: HooksSection;
  skills: SkillsSection;
  agents: AgentsSection;
  memory: MemorySection;
  health: HealthSection;
  parallel: ParallelSection;
  lbrain: LBrainSection;
  doctor: DoctorSection;
  actions: ActionsSection;
}

export interface AuditEntry {
  ts: string;
  action_id: string;
  actor: string;
  params: Record<string, unknown>;
  result: string;
  error?: string;
}

export interface AuditResponse {
  entries: AuditEntry[];
}
