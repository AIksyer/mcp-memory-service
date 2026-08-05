"""Tests for smart_tagger plugin — tagger, config, plugin hooks."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock

import pytest

from memory_os_plugins.smart_tagger.config import (
    SmartTaggerConfig,
    _parse_bool,
    _parse_config_file,
    load_config,
    save_config,
)
from memory_os_plugins.smart_tagger.plugin import (
    before_store_handler,
    on_retrieve_handler,
    register,
)
from memory_os_plugins.smart_tagger.tagger import (
    auto_generate_tags,
    extract_project_from_content,
    get_project_name,
    inject_project_tag,
)


# --------------------------------------------------------------------------- #
#  auto_generate_tags
# --------------------------------------------------------------------------- #

class TestAutoGenerateTags:
    def test_decision_tag(self):
        md = {"content": "We decided to use JWT for authentication."}
        tags = auto_generate_tags(md)
        assert "decision" in tags

    def test_bug_tag(self):
        md = {"content": "Fixed a crash in the parser when input is empty."}
        tags = auto_generate_tags(md)
        assert "bug" in tags
        assert "bug-fix" in tags

    def test_convention_tag(self):
        md = {"content": "We must always use double quotes for strings."}
        tags = auto_generate_tags(md)
        assert "convention" in tags

    def test_learning_tag(self):
        md = {"content": "Learned a lesson: never commit directly to main."}
        tags = auto_generate_tags(md)
        assert "learning" in tags

    def test_database_tag(self):
        md = {"content": "Switched from MySQL to PostgreSQL for better JSON support."}
        tags = auto_generate_tags(md)
        assert "database" in tags

    def test_infra_tag(self):
        md = {"content": "Deploy with Docker and k8s for production."}
        tags = auto_generate_tags(md)
        assert "infra" in tags

    def test_frontend_tag(self):
        md = {"content": "Using React with CSS modules for the frontend."}
        tags = auto_generate_tags(md)
        assert "frontend" in tags

    def test_backend_tag(self):
        md = {"content": "The FastAPI backend exposes a REST API endpoint."}
        tags = auto_generate_tags(md)
        assert "backend" in tags

    def test_security_tag(self):
        md = {"content": "Added OAuth and JWT token validation for security."}
        tags = auto_generate_tags(md)
        assert "security" in tags

    def test_testing_tag(self):
        md = {"content": "Added pytest unit tests with 90% coverage."}
        tags = auto_generate_tags(md)
        assert "testing" in tags

    def test_preference_tag(self):
        md = {"content": "User prefers dark mode over light mode."}
        tags = auto_generate_tags(md)
        assert "preference" in tags

    def test_reference_tag(self):
        md = {"content": "See the official documentation for reference."}
        tags = auto_generate_tags(md)
        assert "reference" in tags

    def test_multiple_tags(self):
        md = {"content": "We decided to fix the database bug in the FastAPI backend."}
        tags = auto_generate_tags(md)
        assert "decision" in tags
        assert "bug" in tags
        assert "database" in tags
        assert "backend" in tags

    def test_no_matching_tags(self):
        md = {"content": "Hello world, this is a simple message."}
        tags = auto_generate_tags(md)
        # Should still have a date tag.
        assert any(t.startswith("date:") for t in tags)

    def test_project_path_extraction_windows(self):
        md = {"content": "Working in G:\\Project\\mcp-memory-service on the plugin."}
        tags = auto_generate_tags(md)
        assert "project:mcp-memory-service" in tags

    def test_project_path_extraction_unix(self):
        md = {"content": "Files at /home/user/my-project/src/main.py"}
        tags = auto_generate_tags(md)
        assert "project:my-project" in tags

    def test_project_path_skip_common_dirs(self):
        """Should not extract 'src' or 'test' as project name."""
        md = {"content": "Path: G:\\Project\\MyApp\\src\\utils.py"}
        tags = auto_generate_tags(md)
        # Should extract 'MyApp' not 'src'
        assert "project:MyApp" in tags
        assert "project:src" not in tags

    def test_date_tag_from_created_at_iso(self):
        md = {
            "content": "Test memory",
            "created_at_iso": "2026-07-15T10:30:00Z",
        }
        tags = auto_generate_tags(md)
        assert "date:2026-07" in tags

    def test_date_tag_fallback_to_current(self):
        md = {"content": "No timestamp provided"}
        tags = auto_generate_tags(md)
        date_tags = [t for t in tags if t.startswith("date:")]
        assert len(date_tags) == 1

    def test_merges_with_existing_tags(self):
        """Existing tags should be preserved, not overwritten."""
        md = {
            "content": "We decided to use PostgreSQL.",
            "tags": ["existing-tag", "custom"],
        }
        tags = auto_generate_tags(md)
        assert "existing-tag" in tags
        assert "custom" in tags
        assert "decision" in tags
        assert "database" in tags

    def test_does_not_duplicate_existing_tags(self):
        """If 'decision' already in tags, should not be duplicated."""
        md = {
            "content": "We decided to use PostgreSQL.",
            "tags": ["decision"],
        }
        tags = auto_generate_tags(md)
        assert tags.count("decision") == 1

    def test_empty_content(self):
        md = {"content": ""}
        tags = auto_generate_tags(md)
        # Should still have date tag.
        assert any(t.startswith("date:") for t in tags)

    def test_no_content_key(self):
        md = {}
        tags = auto_generate_tags(md)
        assert isinstance(tags, list)


# --------------------------------------------------------------------------- #
#  extract_project_from_content
# --------------------------------------------------------------------------- #

class TestExtractProjectFromContent:
    def test_windows_path(self):
        assert extract_project_from_content("G:\\Project\\MyApp\\file.py") == "MyApp"

    def test_windows_path_multiple_segments(self):
        result = extract_project_from_content("C:\\Users\\test\\workspace\\my-project")
        assert result == "my-project"

    def test_unix_path(self):
        assert extract_project_from_content("/home/user/myapp/src/main.py") == "myapp"

    def test_mac_path(self):
        assert extract_project_from_content("/Users/john/MyProject/index.js") == "MyProject"

    def test_explicit_project_prefix(self):
        assert extract_project_from_content("project: my-awesome-project") == "my-awesome-project"

    def test_path_prefix(self):
        assert extract_project_from_content("path: G:\\Code\\test-repo") == "test-repo"

    def test_no_path_found(self):
        assert extract_project_from_content("Just some text without paths") is None

    def test_skips_common_dirs(self):
        result = extract_project_from_content("G:\\Project\\src\\utils.py")
        # Should skip 'src' and get 'Project'
        assert result == "Project"

    def test_multiple_paths_returns_last_meaningful(self):
        content = "G:\\Project\\AppA and /home/user/AppB"
        result = extract_project_from_content(content)
        # Last match wins (AppB from Unix path)
        assert result == "AppB"


# --------------------------------------------------------------------------- #
#  inject_project_tag
# --------------------------------------------------------------------------- #

class TestInjectProjectTag:
    def test_injects_tag(self):
        md = {"content": "test", "tags": ["existing"]}
        result = inject_project_tag(md, "my-project")
        assert "project:my-project" in result["tags"]
        assert "existing" in result["tags"]

    def test_no_duplicate(self):
        md = {"content": "test", "tags": ["project:my-project"]}
        result = inject_project_tag(md, "my-project")
        assert result["tags"].count("project:my-project") == 1

    def test_empty_project_name_noop(self):
        md = {"content": "test", "tags": ["existing"]}
        result = inject_project_tag(md, "")
        assert "project:" not in str(result["tags"])

    def test_creates_tags_key_if_missing(self):
        md = {"content": "test"}
        result = inject_project_tag(md, "my-project")
        assert "project:my-project" in result["tags"]

    def test_returns_same_dict(self):
        """Should modify in-place and return the same object."""
        md = {"content": "test", "tags": []}
        result = inject_project_tag(md, "test-project")
        assert result is md


# --------------------------------------------------------------------------- #
#  get_project_name
# --------------------------------------------------------------------------- #

class TestGetProjectName:
    def test_env_var_priority(self, monkeypatch):
        monkeypatch.setenv("MEMORY_OS_PROJECT_NAME", "env-project")
        assert get_project_name("config-project") == "env-project"

    def test_config_fallback(self, monkeypatch):
        monkeypatch.delenv("MEMORY_OS_PROJECT_NAME", raising=False)
        assert get_project_name("config-project") == "config-project"

    def test_cwd_fallback(self, monkeypatch):
        monkeypatch.delenv("MEMORY_OS_PROJECT_NAME", raising=False)
        # config_project_name is empty — should use cwd basename
        result = get_project_name("")
        assert isinstance(result, str)
        assert len(result) > 0


# --------------------------------------------------------------------------- #
#  Config tests
# --------------------------------------------------------------------------- #

class TestSmartTaggerConfig:
    def test_defaults(self):
        c = SmartTaggerConfig()
        assert c.enabled is True
        assert c.project_name == ""
        assert c.project_filter is False
        assert c.auto_tags is True
        assert c.mistake_boost == 0.15


class TestParseBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "on", "1"])
    def test_truthy(self, value):
        assert _parse_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "no", "off", "0", "", "random"])
    def test_falsy(self, value):
        assert _parse_bool(value) is False


class TestParseConfigFile:
    def test_basic(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text(
            "smart_tagger_enabled: false\n"
            "smart_tagger_project_name: MyProject\n"
            "smart_tagger_project_filter: true\n"
            "smart_tagger_auto_tags: false\n"
            "smart_tagger_mistake_boost: 0.25\n",
            encoding="utf-8",
        )
        result = _parse_config_file(f)
        assert result["smart_tagger_enabled"] is False
        assert result["smart_tagger_project_name"] == "MyProject"
        assert result["smart_tagger_project_filter"] is True
        assert result["smart_tagger_auto_tags"] is False
        assert result["smart_tagger_mistake_boost"] == 0.25

    def test_comments_and_blanks(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text(
            "# Comment\n"
            "\n"
            "smart_tagger_enabled: true\n"
            "\n"
            "# Another\n"
            "smart_tagger_auto_tags: false\n",
            encoding="utf-8",
        )
        result = _parse_config_file(f)
        assert result == {"smart_tagger_enabled": True, "smart_tagger_auto_tags": False}


class TestLoadConfig:
    def test_defaults_when_no_file_no_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_SMART_TAGGER_"):
                monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config.enabled is True
        assert config.project_name == ""
        assert config.project_filter is False
        assert config.auto_tags is True
        assert config.mistake_boost == 0.15

    def test_file_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "config.yml",
        )
        (tmp_path / "config.yml").write_text(
            "smart_tagger_enabled: false\n"
            "smart_tagger_project_name: FromFile\n"
            "smart_tagger_mistake_boost: 0.3\n",
            encoding="utf-8",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_SMART_TAGGER_"):
                monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config.enabled is False
        assert config.project_name == "FromFile"
        assert config.mistake_boost == 0.3

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "config.yml",
        )
        (tmp_path / "config.yml").write_text(
            "smart_tagger_enabled: false\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_ENABLED", "true")
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_PROJECT_NAME", "EnvProject")
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_MISTAKE_BOOST", "0.5")

        config = load_config()
        assert config.enabled is True
        assert config.project_name == "EnvProject"
        assert config.mistake_boost == 0.5

    def test_env_overrides_defaults_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_ENABLED", "false")
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_PROJECT_FILTER", "true")
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_AUTO_TAGS", "false")

        config = load_config()
        assert config.enabled is False
        assert config.project_filter is True
        assert config.auto_tags is False

    def test_invalid_env_value_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_MISTAKE_BOOST", "not_a_float")

        config = load_config()
        assert config.mistake_boost == 0.15

    def test_corrupt_file_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "config.yml",
        )
        (tmp_path / "config.yml").mkdir()

        config = load_config()
        assert config.enabled is True


class TestSaveConfig:
    def test_round_trip(self, tmp_path):
        cfg_path = tmp_path / "config.yml"
        original = SmartTaggerConfig(
            enabled=False,
            project_name="TestProj",
            project_filter=True,
            auto_tags=False,
            mistake_boost=0.3,
        )
        save_config(original, path=cfg_path)
        assert cfg_path.exists()

        loaded = _parse_config_file(cfg_path)
        assert loaded["smart_tagger_enabled"] is False
        assert loaded["smart_tagger_project_name"] == "TestProj"
        assert loaded["smart_tagger_project_filter"] is True
        assert loaded["smart_tagger_auto_tags"] is False
        assert loaded["smart_tagger_mistake_boost"] == 0.3

    def test_no_project_name_omitted(self, tmp_path):
        cfg_path = tmp_path / "config.yml"
        original = SmartTaggerConfig(project_name="")
        save_config(original, path=cfg_path)
        content = cfg_path.read_text(encoding="utf-8")
        assert "smart_tagger_project_name" not in content

    def test_creates_parent_dir(self, tmp_path):
        cfg_path = tmp_path / "subdir" / "config.yml"
        save_config(SmartTaggerConfig(), path=cfg_path)
        assert cfg_path.exists()

    def test_preserves_other_plugin_config(self, tmp_path):
        """save_config should not overwrite git_sync/r2_backup lines."""
        cfg_path = tmp_path / "config.yml"
        cfg_path.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "base_dir: ~/AgentMemory\n"
            "\n"
            "# Memory OS Smart Tagger configuration\n"
            "smart_tagger_enabled: true\n"
            "smart_tagger_mistake_boost: 0.1\n"
            "\n"
            "# Memory OS R2 Backup configuration\n"
            "r2_backup_enabled: true\n"
            "r2_backup_bucket_name: testbucket\n",
            encoding="utf-8",
        )

        new_config = SmartTaggerConfig(
            enabled=False,
            mistake_boost=0.25,
            project_name="NewProject",
        )
        save_config(new_config, path=cfg_path)

        content = cfg_path.read_text(encoding="utf-8")

        # Other plugin config preserved.
        assert "base_dir: ~/AgentMemory" in content
        assert "r2_backup_enabled: true" in content
        assert "r2_backup_bucket_name: testbucket" in content

        # Smart tagger updated.
        assert "smart_tagger_enabled: false" in content
        assert "smart_tagger_mistake_boost: 0.25" in content
        assert "smart_tagger_project_name: NewProject" in content


# --------------------------------------------------------------------------- #
#  Plugin — register + hooks
# --------------------------------------------------------------------------- #

class FakePluginContext:
    """Minimal PluginContext for testing — records hook subscriptions."""

    def __init__(self):
        self.storage = MagicMock()
        self.service = MagicMock()
        self.hooks: dict[str, list] = {}

    def on(self, hook_name, fn):
        self.hooks.setdefault(hook_name, []).append(fn)


class TestRegister:
    def setup_method(self):
        """Reset global state before each test."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = None

    def test_register_subscribes_hooks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_SMART_TAGGER_"):
                monkeypatch.delenv(key, raising=False)
        # Also clean MEMORY_OS_PROJECT_NAME
        monkeypatch.delenv("MEMORY_OS_PROJECT_NAME", raising=False)

        ctx = FakePluginContext()
        register(ctx)

        assert "before_store" in ctx.hooks
        assert "on_retrieve" in ctx.hooks
        assert len(ctx.hooks["before_store"]) == 1
        assert len(ctx.hooks["on_retrieve"]) == 1

    def test_register_disabled_no_hooks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.smart_tagger.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_SMART_TAGGER_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MEMORY_OS_SMART_TAGGER_ENABLED", "false")

        ctx = FakePluginContext()
        register(ctx)

        assert ctx.hooks == {}


class TestBeforeStoreHandler:
    def setup_method(self):
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig()

    def test_returns_modified_dict_with_tags(self):
        """before_store must return the dict with new tags added."""
        md = {
            "content": "We decided to use PostgreSQL for the backend.",
            "content_hash": "abc123def456",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-05T10:00:00Z",
        }

        result = asyncio.run(before_store_handler(md))

        assert result is md  # same object
        assert "decision" in result["tags"]
        assert "database" in result["tags"]
        assert "backend" in result["tags"]
        assert "date:2026-08" in result["tags"]

    def test_preserves_existing_tags(self):
        md = {
            "content": "Bug fix in the parser.",
            "content_hash": "xyz789",
            "tags": ["custom-tag"],
            "memory_type": "note",
            "metadata": {},
        }

        result = asyncio.run(before_store_handler(md))

        assert "custom-tag" in result["tags"]
        assert "bug" in result["tags"]
        assert "bug-fix" in result["tags"]

    def test_injects_project_tag(self):
        """Should inject project:{name} tag."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(project_name="test-project")

        md = {
            "content": "Simple memory",
            "content_hash": "abc",
            "tags": [],
        }

        result = asyncio.run(before_store_handler(md))

        assert "project:test-project" in result["tags"]

    def test_project_tag_from_env(self, monkeypatch):
        """MEMORY_OS_PROJECT_NAME env var should be used for project tag."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig()

        monkeypatch.setenv("MEMORY_OS_PROJECT_NAME", "env-proj")

        md = {
            "content": "Simple memory",
            "content_hash": "abc",
            "tags": [],
        }

        result = asyncio.run(before_store_handler(md))

        assert "project:env-proj" in result["tags"]

    def test_auto_tags_disabled(self):
        """When auto_tags=False, should only inject project tag."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(auto_tags=False, project_name="proj")

        md = {
            "content": "We decided to use PostgreSQL.",
            "content_hash": "abc",
            "tags": ["existing"],
        }

        result = asyncio.run(before_store_handler(md))

        # No content-based tags should be added.
        assert "decision" not in result["tags"]
        assert "database" not in result["tags"]
        # But project tag should still be added.
        assert "project:proj" in result["tags"]
        # Existing tags preserved.
        assert "existing" in result["tags"]

    def test_no_config_returns_original(self):
        """When _config is None, should return the dict unchanged."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = None

        md = {"content": "test", "tags": ["existing"]}

        result = asyncio.run(before_store_handler(md))

        assert result is md
        assert result["tags"] == ["existing"]

    def test_exception_does_not_propagate(self):
        """Errors in tag generation should be caught, dict returned."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig()

        md = None  # Will cause exception in auto_generate_tags

        result = asyncio.run(before_store_handler(md))

        # Should return the input (None) without raising.
        assert result is None


class TestOnRetrieveHandler:
    def setup_method(self):
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig()

    def test_mistake_note_boost(self):
        """mistake-note tagged results should get boosted similarity."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(mistake_boost=0.2)

        results = [
            {"content": "regular memory", "tags": [], "similarity": 0.8},
            {"content": "error memory", "tags": ["mistake-note"], "similarity": 0.7},
        ]

        result = asyncio.run(on_retrieve_handler("query", results))

        # mistake-note result should be boosted: 0.7 + 0.2 = 0.9 > 0.8
        assert result[0]["tags"] == ["mistake-note"]
        assert result[0]["similarity"] == pytest.approx(0.9)

    def test_error_replay_boost(self):
        """error-replay tagged results should also get boosted."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(mistake_boost=0.3)

        results = [
            {"content": "normal", "tags": [], "similarity": 0.9},
            {"content": "error", "tags": ["error-replay"], "similarity": 0.6},
        ]

        result = asyncio.run(on_retrieve_handler("query", results))

        # 0.6 + 0.3 = 0.9, same as 0.9 — stable sort keeps original order
        assert result[0]["similarity"] == 0.9

    def test_boost_capped_at_1(self):
        """Boost should not push similarity above 1.0."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(mistake_boost=0.5)

        results = [
            {"content": "error", "tags": ["mistake-note"], "similarity": 0.8},
        ]

        result = asyncio.run(on_retrieve_handler("query", results))

        assert result[0]["similarity"] == 1.0  # capped

    def test_no_boost_for_regular_tags(self):
        """Regular (non mistake-note) results should not be boosted."""
        results = [
            {"content": "regular", "tags": ["decision"], "similarity": 0.7},
        ]

        result = asyncio.run(on_retrieve_handler("query", results))

        assert result[0]["similarity"] == 0.7

    def test_empty_results(self):
        result = asyncio.run(on_retrieve_handler("query", []))
        assert result == []

    def test_project_filter_prioritizes_same_project(self):
        """When project_filter is enabled, same-project results come first."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(
            project_filter=True,
            project_name="my-project",
        )

        results = [
            {"content": "other project", "tags": ["project:other"], "similarity": 0.9},
            {"content": "my project", "tags": ["project:my-project"], "similarity": 0.7},
        ]

        result = asyncio.run(on_retrieve_handler("query", results))

        # Same-project result should come first despite lower initial score.
        assert result[0]["tags"] == ["project:my-project"]
        assert result[1]["tags"] == ["project:other"]

    def test_project_filter_no_matching_project(self):
        """When no results match the project, all should be returned (no blocking)."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(
            project_filter=True,
            project_name="my-project",
        )

        results = [
            {"content": "other1", "tags": ["project:other1"], "similarity": 0.8},
            {"content": "other2", "tags": ["project:other2"], "similarity": 0.6},
        ]

        result = asyncio.run(on_retrieve_handler("query", results))

        # Should return all results, sorted by score.
        assert len(result) == 2
        assert result[0]["similarity"] >= result[1]["similarity"]

    def test_no_config_returns_original(self):
        """When _config is None, should return results unchanged."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = None

        results = [{"content": "test", "tags": [], "similarity": 0.5}]

        result = asyncio.run(on_retrieve_handler("query", results))

        assert result is results

    def test_exception_does_not_propagate(self):
        """Errors in on_retrieve should be caught, results returned."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig()

        results = None  # Will cause exception

        result = asyncio.run(on_retrieve_handler("query", results))

        # Should return the input (None) without raising.
        assert result is None

    def test_reranking_after_boost(self):
        """Results should be re-sorted after boosting."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(mistake_boost=0.3)

        results = [
            {"content": "top", "tags": [], "similarity": 0.85},
            {"content": "mistake", "tags": ["mistake-note"], "similarity": 0.7},
            {"content": "bottom", "tags": [], "similarity": 0.6},
        ]

        result = asyncio.run(on_retrieve_handler("query", results))

        # After boost: mistake=0.7+0.3=1.0, top=0.85, bottom=0.6
        assert result[0]["tags"] == ["mistake-note"]
        assert result[1]["similarity"] == 0.85
        assert result[2]["similarity"] == 0.6


# --------------------------------------------------------------------------- #
#  Integration: before_store → on_retrieve end-to-end
# --------------------------------------------------------------------------- #

class TestIntegrationFlow:
    def test_store_then_retrieve(self):
        """Full flow: before_store tags memory, on_retrieve boosts it."""
        from memory_os_plugins.smart_tagger import plugin as pl
        pl._config = SmartTaggerConfig(
            project_name="integration-test",
            mistake_boost=0.2,
        )

        # Step 1: before_store adds tags.
        md = {
            "content": "We learned a lesson: this mistake caused a crash in the database.",
            "content_hash": "integration123",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-05T12:00:00Z",
        }

        tagged = asyncio.run(before_store_handler(md))

        # Verify tags were generated.
        assert "learning" in tagged["tags"]
        assert "bug" in tagged["tags"]
        assert "database" in tagged["tags"]
        assert "project:integration-test" in tagged["tags"]
        assert "date:2026-08" in tagged["tags"]

        # Step 2: on_retrieve boosts mistake-note (simulate adding mistake-note tag).
        tagged["tags"].append("mistake-note")
        tagged["similarity"] = 0.7

        results = [
            {"content": "regular", "tags": [], "similarity": 0.8},
            tagged,
        ]

        reranked = asyncio.run(on_retrieve_handler("query", results))

        # The mistake-note result should be boosted and come first.
        assert reranked[0]["tags"] == tagged["tags"]
        assert reranked[0]["similarity"] > 0.8
