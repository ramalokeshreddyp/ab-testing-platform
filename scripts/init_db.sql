-- Create experiments table
CREATE TABLE IF NOT EXISTS experiments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    config JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Seed initial experiment matching submission.json
INSERT INTO experiments (id, name, description, status, config, created_at, updated_at)
VALUES (
    1,
    'checkout_button_color',
    'Experiment to test conversion rates for blue vs green checkout buttons',
    'ACTIVE',
    '{
        "variants": [
            {"name": "control", "weight": 50},
            {"name": "treatment", "weight": 50}
        ],
        "targeting_rules": [
            {"type": "EQUALS", "attribute": "country", "value": "US"}
        ]
    }'::jsonb,
    NOW(),
    NOW()
) ON CONFLICT (id) DO UPDATE 
SET name = EXCLUDED.name,
    description = EXCLUDED.description,
    status = EXCLUDED.status,
    config = EXCLUDED.config,
    updated_at = NOW();

-- Update the sequence so next insert starts at 2
SELECT setval('experiments_id_seq', (SELECT GREATEST(MAX(id), 1) FROM experiments));
