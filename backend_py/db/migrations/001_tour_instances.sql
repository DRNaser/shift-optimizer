-- ============================================================================
-- MIGRATION 001: Tour Instances (P0 BLOCKER FIX)
-- ============================================================================
-- Problem: tours_normalized.count vs assignments ist logisch kaputt
-- Solution: Explizite tour_instances Tabelle (1:1 mit assignments)
-- ============================================================================

-- 1. Tour-Instanzen-Tabelle
CREATE TABLE IF NOT EXISTS tour_instances (
    id                  SERIAL PRIMARY KEY,
    tour_template_id    INTEGER NOT NULL REFERENCES tours_normalized(id) ON DELETE CASCADE,
    instance_number     INTEGER NOT NULL CHECK (instance_number > 0),
    forecast_version_id INTEGER NOT NULL REFERENCES forecast_versions(id) ON DELETE CASCADE,
    
    -- Kopie von Template-Daten (denormalisiert für Performance)
    day                 INTEGER NOT NULL CHECK (day BETWEEN 1 AND 7),
    start_ts            TIME NOT NULL,
    end_ts              TIME NOT NULL,
    crosses_midnight    BOOLEAN DEFAULT FALSE,
    duration_min        INTEGER NOT NULL CHECK (duration_min > 0),
    work_hours          DECIMAL(5,2) NOT NULL CHECK (work_hours > 0),
    
    -- Optionale Felder vom Template
    depot               VARCHAR(50),
    skill               VARCHAR(50),
    
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    
    CONSTRAINT unique_template_instance UNIQUE (tour_template_id, instance_number),
    CONSTRAINT unique_forecast_instance UNIQUE (forecast_version_id, tour_template_id, instance_number)
);

CREATE INDEX idx_tour_instances_template ON tour_instances(tour_template_id);
CREATE INDEX idx_tour_instances_forecast ON tour_instances(forecast_version_id);
CREATE INDEX idx_tour_instances_day ON tour_instances(day);

COMMENT ON TABLE tour_instances IS 'Expanded tour instances (one row per driver needed)';
COMMENT ON COLUMN tour_instances.instance_number IS '1, 2, 3 for count=3 template';
COMMENT ON COLUMN tour_instances.crosses_midnight IS 'TRUE if end_ts < start_ts';

-- 2. Migrations-Hilfe: Auto-expand existing tours_normalized
CREATE OR REPLACE FUNCTION expand_tour_instances(p_forecast_version_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    v_tour RECORD;
    v_instance INTEGER;
    v_crosses_midnight BOOLEAN;
    v_instances_created INTEGER := 0;
BEGIN
    -- Für jede Tour im Forecast
    FOR v_tour IN 
        SELECT * FROM tours_normalized 
        WHERE forecast_version_id = p_forecast_version_id
    LOOP
        -- Cross-midnight detection
        v_crosses_midnight := (v_tour.end_ts < v_tour.start_ts);
        
        -- Erstelle count Instanzen
        FOR v_instance IN 1..v_tour.count LOOP
            INSERT INTO tour_instances (
                tour_template_id, instance_number, forecast_version_id,
                day, start_ts, end_ts, crosses_midnight, 
                duration_min, work_hours, depot, skill
            ) VALUES (
                v_tour.id, v_instance, p_forecast_version_id,
                v_tour.day, v_tour.start_ts, v_tour.end_ts, v_crosses_midnight,
                v_tour.duration_min, v_tour.work_hours, v_tour.depot, v_tour.skill
            )
            ON CONFLICT (tour_template_id, instance_number) DO NOTHING;
            
            v_instances_created := v_instances_created + 1;
        END LOOP;
    END LOOP;
    
    RETURN v_instances_created;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION expand_tour_instances IS 'Auto-expand tours_normalized.count to tour_instances';

-- 3. Modify assignments: tour_id → tour_instance_id
ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_tour_id_fkey;
ALTER TABLE assignments RENAME COLUMN tour_id TO tour_id_deprecated;
ALTER TABLE assignments ALTER COLUMN tour_id_deprecated DROP NOT NULL;
ALTER TABLE assignments ADD COLUMN tour_instance_id INTEGER;

-- Add foreign key constraint
ALTER TABLE assignments ADD CONSTRAINT fk_tour_instance 
    FOREIGN KEY (tour_instance_id) REFERENCES tour_instances(id) ON DELETE RESTRICT;

-- Update unique constraint
ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_unique_tour_assignment;
ALTER TABLE assignments ADD CONSTRAINT assignments_unique_instance_assignment 
    UNIQUE (plan_version_id, tour_instance_id);

CREATE INDEX idx_assignments_tour_instance ON assignments(tour_instance_id);

-- 4. LOCKED Plan Immutability (CASCADE FIX)
CREATE OR REPLACE FUNCTION prevent_locked_plan_data_modification()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if plan is LOCKED
    IF EXISTS (
        SELECT 1 FROM plan_versions 
        WHERE id = NEW.plan_version_id AND status = 'LOCKED'
    ) THEN
        RAISE EXCEPTION 'Cannot modify data for LOCKED plan_version %', NEW.plan_version_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to assignments
CREATE TRIGGER prevent_locked_assignments
BEFORE INSERT OR UPDATE OR DELETE ON assignments
FOR EACH ROW
EXECUTE FUNCTION prevent_locked_plan_data_modification();

COMMENT ON TRIGGER prevent_locked_assignments ON assignments IS 'Prevent modifications to LOCKED plan assignments';

-- 5. Audit log: APPEND-only for LOCKED plans
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    -- Allow INSERT always (append-only)
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    
    -- Prevent UPDATE/DELETE on LOCKED plans
    IF EXISTS (
        SELECT 1 FROM plan_versions 
        WHERE id = OLD.plan_version_id AND status = 'LOCKED'
    ) THEN
        RAISE EXCEPTION 'Cannot modify/delete audit log for LOCKED plan_version %', OLD.plan_version_id;
    END IF;
    
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_audit_log_modification_trigger
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_log_modification();

-- 6. Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 001 applied: tour_instances table created';
    RAISE NOTICE '   - assignments.tour_id → tour_instance_id';
    RAISE NOTICE '   - LOCKED plan immutability enforced (assignments + audit_log)';
    RAISE NOTICE '   - Use expand_tour_instances(forecast_version_id) to populate';
END $$;
