"""SQLite schema for LBrain."""

PHASE_1A_TABLES = {
    "brain_projects",
    "brain_passports",
    "brain_attempts",
    "brain_context_decisions",
}

PHASE_1B_TABLES = {
    "brain_decisions",
    "brain_capture_events",
    "brain_memory_candidates",
}

PHASE_1C_TABLES = {
    "brain_contracts",
    "brain_contract_events",
}

PHASE_1D_TABLES = {
    "brain_change_receipts",
    "brain_change_receipt_events",
}

LBRAIN_TABLES = PHASE_1A_TABLES | PHASE_1B_TABLES | PHASE_1C_TABLES | PHASE_1D_TABLES


def init_schema(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS brain_projects (
            id INTEGER PRIMARY KEY,
            root_path_hash TEXT NOT NULL,
            root_path_display TEXT,
            repo_id TEXT,
            git_remote_hash TEXT,
            git_branch TEXT,
            name TEXT,
            platform TEXT,
            shell_mode TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(root_path_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_projects_root_path_hash
            ON brain_projects(root_path_hash);
        CREATE INDEX IF NOT EXISTS idx_brain_projects_repo_id
            ON brain_projects(repo_id);
        CREATE INDEX IF NOT EXISTS idx_brain_projects_git_remote_hash
            ON brain_projects(git_remote_hash);

        CREATE TABLE IF NOT EXISTS brain_passports (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            stack_json TEXT NOT NULL,
            commands_json TEXT NOT NULL,
            paths_json TEXT NOT NULL,
            rules_json TEXT NOT NULL,
            architecture_summary TEXT,
            danger_zones_json TEXT NOT NULL,
            manual_overrides_json TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            source TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            privacy_class TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, version),
            FOREIGN KEY(project_id) REFERENCES brain_projects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_passports_project_id
            ON brain_passports(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_passports_project_version
            ON brain_passports(project_id, version);
        CREATE INDEX IF NOT EXISTS idx_brain_passports_detected_at
            ON brain_passports(detected_at);

        CREATE TABLE IF NOT EXISTS brain_attempts (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            attempted_action TEXT NOT NULL,
            command_redacted TEXT,
            command_fingerprint TEXT,
            files_touched_json TEXT NOT NULL,
            error_summary TEXT,
            root_cause TEXT,
            why_failed TEXT,
            replacement_approach TEXT,
            platform TEXT,
            retry_policy TEXT NOT NULL,
            status TEXT NOT NULL,
            source_session_id TEXT,
            confidence INTEGER NOT NULL,
            privacy_class TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen_at TEXT,
            FOREIGN KEY(project_id) REFERENCES brain_projects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_attempts_project_id
            ON brain_attempts(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_attempts_command_fingerprint
            ON brain_attempts(command_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_brain_attempts_project_retry_policy
            ON brain_attempts(project_id, retry_policy);
        CREATE INDEX IF NOT EXISTS idx_brain_attempts_last_seen_at
            ON brain_attempts(last_seen_at);

        CREATE TABLE IF NOT EXISTS brain_context_decisions (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            session_id TEXT,
            target TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            priority INTEGER NOT NULL,
            relevance_score REAL,
            token_estimate INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_brain_context_project_session
            ON brain_context_decisions(project_id, session_id);
        CREATE INDEX IF NOT EXISTS idx_brain_context_target
            ON brain_context_decisions(target);
        CREATE INDEX IF NOT EXISTS idx_brain_context_item
            ON brain_context_decisions(item_type, item_id);
        CREATE INDEX IF NOT EXISTS idx_brain_context_created_at
            ON brain_context_decisions(created_at);

        CREATE TABLE IF NOT EXISTS brain_decisions (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            scope TEXT NOT NULL DEFAULT 'project',
            key TEXT NOT NULL,
            title TEXT NOT NULL,
            decision TEXT NOT NULL,
            rationale TEXT,
            enforcement_hint TEXT,
            applies_to_json TEXT NOT NULL,
            forbidden_patterns_json TEXT NOT NULL,
            required_patterns_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            source TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            status TEXT NOT NULL,
            privacy_class TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            supersedes_key TEXT,
            UNIQUE(project_id, key),
            FOREIGN KEY(project_id) REFERENCES brain_projects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_decisions_project_id
            ON brain_decisions(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_decisions_key
            ON brain_decisions(key);
        CREATE INDEX IF NOT EXISTS idx_brain_decisions_status
            ON brain_decisions(status);
        CREATE INDEX IF NOT EXISTS idx_brain_decisions_project_key
            ON brain_decisions(project_id, key);
        CREATE INDEX IF NOT EXISTS idx_brain_decisions_updated_at
            ON brain_decisions(updated_at);

        CREATE TABLE IF NOT EXISTS brain_capture_events (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            session_id TEXT,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            summary TEXT NOT NULL,
            command_fingerprint TEXT,
            command_preview_redacted TEXT,
            path TEXT,
            evidence_json TEXT NOT NULL,
            confidence_delta INTEGER NOT NULL,
            privacy_class TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES brain_projects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_capture_events_project_id
            ON brain_capture_events(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_capture_events_session_id
            ON brain_capture_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_brain_capture_events_event_type
            ON brain_capture_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_brain_capture_events_command_fingerprint
            ON brain_capture_events(command_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_brain_capture_events_created_at
            ON brain_capture_events(created_at);

        CREATE TABLE IF NOT EXISTS brain_memory_candidates (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            scope TEXT NOT NULL DEFAULT 'project',
            candidate_type TEXT NOT NULL,
            key TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            rationale TEXT,
            proposed_target TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            privacy_class TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            promoted_to_type TEXT,
            promoted_to_id INTEGER,
            UNIQUE(project_id, candidate_type, key),
            FOREIGN KEY(project_id) REFERENCES brain_projects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_memory_candidates_project_id
            ON brain_memory_candidates(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_memory_candidates_candidate_type
            ON brain_memory_candidates(candidate_type);
        CREATE INDEX IF NOT EXISTS idx_brain_memory_candidates_key
            ON brain_memory_candidates(key);
        CREATE INDEX IF NOT EXISTS idx_brain_memory_candidates_status
            ON brain_memory_candidates(status);
        CREATE INDEX IF NOT EXISTS idx_brain_memory_candidates_confidence
            ON brain_memory_candidates(confidence);
        CREATE INDEX IF NOT EXISTS idx_brain_memory_candidates_updated_at
            ON brain_memory_candidates(updated_at);

        CREATE TABLE IF NOT EXISTS brain_contracts (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            session_id TEXT,
            title TEXT,
            task_goal TEXT NOT NULL,
            mode TEXT NOT NULL,
            allowed_files_json TEXT NOT NULL,
            forbidden_files_json TEXT NOT NULL,
            allowed_commands_json TEXT NOT NULL,
            forbidden_commands_json TEXT NOT NULL,
            max_files_changed INTEGER,
            max_lines_changed INTEGER,
            required_tests_json TEXT NOT NULL,
            recorded_tests_json TEXT NOT NULL DEFAULT '[]',
            stop_conditions_json TEXT NOT NULL,
            review_checklist_json TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL,
            violation_count INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL,
            source TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            privacy_class TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            started_at TEXT,
            closed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES brain_projects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_contracts_project_id
            ON brain_contracts(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_contracts_session_id
            ON brain_contracts(session_id);
        CREATE INDEX IF NOT EXISTS idx_brain_contracts_status
            ON brain_contracts(status);
        CREATE INDEX IF NOT EXISTS idx_brain_contracts_project_status
            ON brain_contracts(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_brain_contracts_created_at
            ON brain_contracts(created_at);
        CREATE INDEX IF NOT EXISTS idx_brain_contracts_updated_at
            ON brain_contracts(updated_at);

        CREATE TABLE IF NOT EXISTS brain_contract_events (
            id INTEGER PRIMARY KEY,
            contract_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            session_id TEXT,
            event_type TEXT NOT NULL,
            tool_name TEXT,
            path TEXT,
            command_preview_redacted TEXT,
            command_fingerprint TEXT,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(contract_id) REFERENCES brain_contracts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_contract_events_contract_id
            ON brain_contract_events(contract_id);
        CREATE INDEX IF NOT EXISTS idx_brain_contract_events_project_id
            ON brain_contract_events(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_contract_events_project_session
            ON brain_contract_events(project_id, session_id);
        CREATE INDEX IF NOT EXISTS idx_brain_contract_events_event_type
            ON brain_contract_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_brain_contract_events_created_at
            ON brain_contract_events(created_at);

        CREATE TABLE IF NOT EXISTS brain_change_receipts (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            contract_id INTEGER,
            title TEXT,
            goal TEXT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finalized_at TEXT,
            git_root TEXT NOT NULL,
            branch TEXT,
            base_commit TEXT NOT NULL,
            head_commit TEXT,
            base_equals_head INTEGER,
            working_tree_dirty_start INTEGER NOT NULL,
            working_tree_dirty_end INTEGER,
            files_changed_json TEXT NOT NULL,
            diff_stat_json TEXT NOT NULL,
            commands_json TEXT NOT NULL,
            tests_json TEXT NOT NULL,
            contract_check_json TEXT NOT NULL,
            decision_check_json TEXT NOT NULL,
            capture_event_ids_json TEXT NOT NULL,
            auto_learned_ids_json TEXT NOT NULL,
            summary TEXT,
            review_notes TEXT,
            undo_hint TEXT,
            redaction_status TEXT NOT NULL,
            privacy_class TEXT NOT NULL DEFAULT 'local-only',
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES brain_projects(id),
            FOREIGN KEY(contract_id) REFERENCES brain_contracts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipts_project_id
            ON brain_change_receipts(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipts_contract_id
            ON brain_change_receipts(contract_id);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipts_status
            ON brain_change_receipts(status);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipts_project_status
            ON brain_change_receipts(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipts_updated_at
            ON brain_change_receipts(updated_at);

        CREATE TABLE IF NOT EXISTS brain_change_receipt_events (
            id INTEGER PRIMARY KEY,
            receipt_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            command TEXT,
            path TEXT,
            evidence_json TEXT NOT NULL,
            capture_event_id INTEGER,
            created_at TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            FOREIGN KEY(receipt_id) REFERENCES brain_change_receipts(id),
            FOREIGN KEY(project_id) REFERENCES brain_projects(id),
            FOREIGN KEY(capture_event_id) REFERENCES brain_capture_events(id)
        );
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipt_events_receipt_id
            ON brain_change_receipt_events(receipt_id);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipt_events_project_id
            ON brain_change_receipt_events(project_id);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipt_events_type
            ON brain_change_receipt_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipt_events_capture_event
            ON brain_change_receipt_events(capture_event_id);
        CREATE INDEX IF NOT EXISTS idx_brain_change_receipt_events_created_at
            ON brain_change_receipt_events(created_at);
        """
    )
    _ensure_column(con, "brain_decisions", "scope", "TEXT NOT NULL DEFAULT 'project'")
    _ensure_column(con, "brain_memory_candidates", "scope", "TEXT NOT NULL DEFAULT 'project'")
    con.execute("CREATE INDEX IF NOT EXISTS idx_brain_decisions_scope ON brain_decisions(scope)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_brain_memory_candidates_scope ON brain_memory_candidates(scope)")
    con.commit()


def _ensure_column(con, table, column, definition):
    columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def existing_tables(con):
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def missing_phase_1a_tables(con):
    return sorted(PHASE_1A_TABLES - existing_tables(con))


def missing_phase_1b_tables(con):
    return sorted(PHASE_1B_TABLES - existing_tables(con))


def missing_phase_1c_tables(con):
    return sorted(PHASE_1C_TABLES - existing_tables(con))


def missing_phase_1d_tables(con):
    return sorted(PHASE_1D_TABLES - existing_tables(con))


def missing_lbrain_tables(con):
    return sorted(LBRAIN_TABLES - existing_tables(con))
