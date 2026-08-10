-- Copyright 2024 Heinrich Krupp
-- Modifications Copyright 2026 AIksyer
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.
-- v4: Add sync_version and device_id columns to memories table
-- sync_version: incremented on every write (store=1, each update+1)
-- device_id: identifies which device wrote the memory
ALTER TABLE memories ADD COLUMN sync_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE memories ADD COLUMN device_id TEXT;
