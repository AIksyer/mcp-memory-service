-- v4: Add sync_version and device_id columns to memories table
-- sync_version: incremented on every write (store=1, each update+1)
-- device_id: identifies which device wrote the memory
ALTER TABLE memories ADD COLUMN sync_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE memories ADD COLUMN device_id TEXT;
