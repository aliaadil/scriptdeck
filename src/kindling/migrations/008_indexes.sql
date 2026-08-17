-- NEW for v2.0.
CREATE INDEX idx_runs_script_started ON runs(script_id, started_at DESC);
CREATE INDEX idx_schedules_due ON schedules(enabled, next_run_at);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_audit_user_at ON audit_log(user_id, at DESC);