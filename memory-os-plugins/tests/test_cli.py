"""Tests for cli.main — init, status, export, import, and pull commands."""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from memory_os_plugins.cli.main import cli


# --------------------------------------------------------------------------- #
#  init command
# --------------------------------------------------------------------------- #

class TestInitCommand:
    def test_init_creates_repo_and_config(self, tmp_path):
        repo_path = tmp_path / "AgentMemory"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(cli, ["init", "--repo", str(repo_path)])

        assert result.exit_code == 0
        assert "Git sync repository initialized" in result.output
        assert str(repo_path) in result.output
        assert "Configuration written to" in result.output

        # Repo structure.
        assert (repo_path / ".git").exists()
        assert (repo_path / "memories").exists()
        assert (repo_path / ".gitignore").exists()

        # Config file.
        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "enabled: true" in content
        assert str(repo_path) in content

    def test_init_with_project_name(self, tmp_path):
        repo_path = tmp_path / "AgentMemory"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(
                cli, ["init", "--repo", str(repo_path), "--project", "MyProject"]
            )

        assert result.exit_code == 0
        assert "MyProject" in result.output

        content = config_path.read_text(encoding="utf-8")
        assert "project_name: MyProject" in content

    def test_init_default_repo_path(self, tmp_path, monkeypatch):
        """When --repo not given, should default to ~/AgentMemory."""
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        # On Windows, Path.home() uses USERPROFILE.
        monkeypatch.setenv("USERPROFILE", str(fake_home))

        config_path = tmp_path / "config.yml"
        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(cli, ["init"])

        assert result.exit_code == 0
        assert (fake_home / "AgentMemory").exists()

    def test_init_git_init_failure(self, tmp_path):
        """If git_init fails, exit code should be 1."""
        repo_path = tmp_path / "repo"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.cli.main.git_init", return_value=False
        ):
            result = runner.invoke(cli, ["init", "--repo", str(repo_path)])

        assert result.exit_code == 1


# --------------------------------------------------------------------------- #
#  init --enable-r2-sync
# --------------------------------------------------------------------------- #

class TestInitR2Sync:
    def test_r2_sync_creates_workflow_file(self, tmp_path):
        """--enable-r2-sync should create .github/workflows/r2-sync.yml."""
        repo_path = tmp_path / "AgentMemory"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(
                cli, ["init", "--repo", str(repo_path), "--enable-r2-sync"]
            )

        assert result.exit_code == 0
        workflow_file = repo_path / ".github" / "workflows" / "r2-sync.yml"
        assert workflow_file.exists()
        content = workflow_file.read_text(encoding="utf-8")
        assert "Sync Memories to R2" in content
        assert "sync-to-r2" in content
        assert "memories/**" in content
        assert "R2_ACCESS_KEY_ID" in content
        assert "R2_SECRET_ACCESS_KEY" in content
        assert "R2_ACCOUNT_ID" in content
        assert "R2_BUCKET_NAME" in content

    def test_r2_sync_disabled_by_default(self, tmp_path):
        """Without --enable-r2-sync, no workflow file should be created."""
        repo_path = tmp_path / "AgentMemory"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(cli, ["init", "--repo", str(repo_path)])

        assert result.exit_code == 0
        workflow_file = repo_path / ".github" / "workflows" / "r2-sync.yml"
        assert not workflow_file.exists()

    def test_r2_sync_prints_secret_instructions(self, tmp_path):
        """Output should mention all 4 required GitHub Secrets."""
        repo_path = tmp_path / "AgentMemory"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(
                cli, ["init", "--repo", str(repo_path), "--enable-r2-sync"]
            )

        assert result.exit_code == 0
        assert "R2_ACCESS_KEY_ID" in result.output
        assert "R2_SECRET_ACCESS_KEY" in result.output
        assert "R2_ACCOUNT_ID" in result.output
        assert "R2_BUCKET_NAME" in result.output
        assert "GitHub Secrets" in result.output

    def test_r2_sync_workflow_has_permissions(self, tmp_path):
        """Workflow should include permissions: contents: read."""
        repo_path = tmp_path / "AgentMemory"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(
                cli, ["init", "--repo", str(repo_path), "--enable-r2-sync"]
            )

        assert result.exit_code == 0
        content = (repo_path / ".github" / "workflows" / "r2-sync.yml").read_text(
            encoding="utf-8"
        )
        assert "permissions:" in content
        assert "contents: read" in content

    def test_r2_sync_workflow_uses_ubuntu_latest(self, tmp_path):
        """Workflow should run on ubuntu-latest."""
        repo_path = tmp_path / "AgentMemory"
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(
                cli, ["init", "--repo", str(repo_path), "--enable-r2-sync"]
            )

        assert result.exit_code == 0
        content = (repo_path / ".github" / "workflows" / "r2-sync.yml").read_text(
            encoding="utf-8"
        )
        assert "ubuntu-latest" in content


# --------------------------------------------------------------------------- #
#  status command
# --------------------------------------------------------------------------- #

class TestStatusCommand:
    def test_status_shows_config_values(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        (repo_path / "memories").mkdir()

        config_path = tmp_path / "config.yml"
        config_path.write_text(
            f"enabled: true\nrepo_path: {repo_path}\nauto_push: false\n"
            f"batch_size: 5\nbatch_timeout: 30\nproject_name: TestProj\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Enabled:       yes" in result.output
        assert str(repo_path) in result.output
        assert "Auto push:     no" in result.output
        assert "Batch size:    5" in result.output
        assert "Batch timeout: 30s" in result.output
        assert "Project:       TestProj" in result.output
        assert "MD files:      0" in result.output

    def test_status_repo_not_found(self, tmp_path):
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            f"enabled: true\nrepo_path: {tmp_path / 'nonexistent'}\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Repository not found" in result.output

    def test_status_with_md_files(self, tmp_path):
        repo_path = tmp_path / "repo"
        memories = repo_path / "memories"
        (memories / "ab").mkdir(parents=True)
        (memories / "ab" / "hash1.md").write_text("content", encoding="utf-8")
        (memories / "cd" / "hash2.md").parent.mkdir(parents=True)
        (memories / "cd" / "hash2.md").write_text("content", encoding="utf-8")

        config_path = tmp_path / "config.yml"
        config_path.write_text(
            f"enabled: true\nrepo_path: {repo_path}\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "MD files:      2" in result.output

    def test_status_shows_last_commit(self, tmp_path):
        """Status should show the last git commit if the repo has one."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        subprocess.run(
            ["git", "init"], cwd=str(repo_path), capture_output=True
        )
        # Set local git identity so commit works.
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(repo_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(repo_path), capture_output=True,
        )
        (repo_path / "memories").mkdir()
        (repo_path / "test.txt").write_text("hello", encoding="utf-8")
        subprocess.run(
            ["git", "add", "-A"], cwd=str(repo_path), capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "test commit message"],
            cwd=str(repo_path), capture_output=True,
        )

        config_path = tmp_path / "config.yml"
        config_path.write_text(
            f"enabled: true\nrepo_path: {repo_path}\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch(
            "memory_os_plugins.cli.main.CONFIG_FILE", config_path
        ), patch(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", config_path
        ):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "test commit message" in result.output


# --------------------------------------------------------------------------- #
#  export command
# --------------------------------------------------------------------------- #

class TestExportCommand:
    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryExporter")
    def test_export_basic(self, mock_exporter_cls, mock_create_storage, tmp_path):
        """Export should call MemoryExporter.export_to_json and show summary."""
        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_exporter = MagicMock()
        mock_exporter.export_to_json = AsyncMock(return_value={
            "success": True,
            "exported_count": 42,
            "output_file": str(tmp_path / "out.json"),
            "file_size_bytes": 1048576,
            "source_machine": "test-machine",
            "export_timestamp": "2026-08-03T00:00:00",
        })
        mock_exporter_cls.return_value = mock_exporter

        runner = CliRunner()
        output_file = tmp_path / "out.json"
        result = runner.invoke(cli, ["export", "--output", str(output_file)])

        assert result.exit_code == 0
        mock_exporter.export_to_json.assert_called_once()
        call_kwargs = mock_exporter.export_to_json.call_args
        assert call_kwargs.args[0] == output_file
        assert call_kwargs.kwargs["include_embeddings"] is False
        assert call_kwargs.kwargs["filter_tags"] is None
        assert "Export complete: 42 memories" in result.output
        assert "1.00 MB" in result.output
        assert "test-machine" in result.output

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryExporter")
    def test_export_with_embeddings_and_tags(self, mock_exporter_cls, mock_create_storage, tmp_path):
        """Export with --include-embeddings and --filter-tags."""
        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_exporter = MagicMock()
        mock_exporter.export_to_json = AsyncMock(return_value={
            "success": True,
            "exported_count": 5,
            "output_file": str(tmp_path / "out.json"),
            "file_size_bytes": 2048,
            "source_machine": "host",
            "export_timestamp": "2026-08-03T00:00:00",
        })
        mock_exporter_cls.return_value = mock_exporter

        runner = CliRunner()
        output_file = tmp_path / "out.json"
        result = runner.invoke(cli, [
            "export", "-o", str(output_file),
            "--include-embeddings",
            "--filter-tags", "tag1,tag2",
        ])

        assert result.exit_code == 0
        call_kwargs = mock_exporter.export_to_json.call_args
        assert call_kwargs.kwargs["include_embeddings"] is True
        assert call_kwargs.kwargs["filter_tags"] == ["tag1", "tag2"]
        assert "Export complete: 5 memories" in result.output

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryExporter")
    def test_export_db_not_found(self, mock_exporter_cls, mock_create_storage, tmp_path):
        """Export should exit 1 when database file is not found."""
        mock_create_storage.side_effect = FileNotFoundError("Database file not found: /missing.db")

        runner = CliRunner()
        result = runner.invoke(cli, ["export", "-o", str(tmp_path / "out.json")])

        assert result.exit_code == 1
        assert "Error" in result.output
        mock_exporter_cls.assert_not_called()

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryExporter")
    def test_export_generic_error(self, mock_exporter_cls, mock_create_storage, tmp_path):
        """Export should exit 1 on unexpected errors."""
        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_exporter = MagicMock()
        mock_exporter.export_to_json = AsyncMock(side_effect=RuntimeError("disk full"))
        mock_exporter_cls.return_value = mock_exporter

        runner = CliRunner()
        result = runner.invoke(cli, ["export", "-o", str(tmp_path / "out.json")])

        assert result.exit_code == 1
        assert "Error during export" in result.output

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryExporter")
    def test_export_empty_filter_tags(self, mock_exporter_cls, mock_create_storage, tmp_path):
        """--filter-tags with empty string should be treated as None."""
        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_exporter = MagicMock()
        mock_exporter.export_to_json = AsyncMock(return_value={
            "success": True,
            "exported_count": 0,
            "output_file": str(tmp_path / "out.json"),
            "file_size_bytes": 100,
            "source_machine": "host",
            "export_timestamp": "2026-08-03T00:00:00",
        })
        mock_exporter_cls.return_value = mock_exporter

        runner = CliRunner()
        result = runner.invoke(cli, [
            "export", "-o", str(tmp_path / "out.json"),
            "--filter-tags", "",
        ])

        assert result.exit_code == 0
        call_kwargs = mock_exporter.export_to_json.call_args
        assert call_kwargs.kwargs["filter_tags"] is None

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryExporter")
    def test_export_requires_output(self, mock_exporter_cls, mock_create_storage, tmp_path):
        """Export without --output should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, ["export"])
        assert result.exit_code != 0
        mock_exporter_cls.assert_not_called()

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryExporter")
    def test_export_closes_storage(self, mock_exporter_cls, mock_create_storage, tmp_path):
        """Export should call storage.close() in the finally block."""
        mock_storage = MagicMock()
        mock_storage.close = AsyncMock()
        mock_create_storage.return_value = mock_storage

        mock_exporter = MagicMock()
        mock_exporter.export_to_json = AsyncMock(return_value={
            "success": True,
            "exported_count": 1,
            "output_file": str(tmp_path / "out.json"),
            "file_size_bytes": 50,
            "source_machine": "host",
            "export_timestamp": "2026-08-03T00:00:00",
        })
        mock_exporter_cls.return_value = mock_exporter

        runner = CliRunner()
        result = runner.invoke(cli, ["export", "-o", str(tmp_path / "out.json")])
        assert result.exit_code == 0
        mock_storage.close.assert_called_once()


# --------------------------------------------------------------------------- #
#  import command
# --------------------------------------------------------------------------- #

class TestImportCommand:
    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_basic(self, mock_importer_cls, mock_create_storage, tmp_path):
        """Import should call MemoryImporter.import_from_json and show summary."""
        input_file = tmp_path / "memories.json"
        input_file.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_importer = MagicMock()
        mock_importer.import_from_json = AsyncMock(return_value={
            "files_processed": 1,
            "total_processed": 10,
            "imported": 8,
            "duplicates_skipped": 2,
            "errors": 0,
            "sources": {"remote-host": {"total": 10, "imported": 8, "duplicates": 2}},
            "dry_run": False,
            "start_time": "2026-08-03T00:00:00",
            "end_time": "2026-08-03T00:00:01",
        })
        mock_importer_cls.return_value = mock_importer

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(input_file)])

        assert result.exit_code == 0
        mock_importer.import_from_json.assert_called_once()
        call_kwargs = mock_importer.import_from_json.call_args
        assert call_kwargs.args[0] == [input_file]
        assert call_kwargs.kwargs["deduplicate"] is True
        assert call_kwargs.kwargs["add_source_tags"] is True
        assert call_kwargs.kwargs["dry_run"] is False
        assert "Import complete:" in result.output
        assert "8" in result.output
        assert "2" in result.output

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_dry_run(self, mock_importer_cls, mock_create_storage, tmp_path):
        """--dry-run should call analyze_import instead of import_from_json."""
        input_file = tmp_path / "memories.json"
        input_file.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_importer = MagicMock()
        mock_importer.analyze_import = AsyncMock(return_value={
            "files": [],
            "total_memories": 15,
            "unique_memories": 12,
            "potential_duplicates": 3,
            "sources": {"remote": {"files": 1, "total_memories": 15, "new_memories": 12}},
            "conflicts": [],
        })
        mock_importer_cls.return_value = mock_importer

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(input_file), "--dry-run"])

        assert result.exit_code == 0
        mock_importer.analyze_import.assert_called_once()
        mock_importer.import_from_json.assert_not_called()
        assert "Dry-run analysis complete:" in result.output
        assert "15" in result.output
        assert "12" in result.output
        assert "3" in result.output

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_no_deduplicate(self, mock_importer_cls, mock_create_storage, tmp_path):
        """--no-deduplicate should pass deduplicate=False."""
        input_file = tmp_path / "memories.json"
        input_file.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_importer = MagicMock()
        mock_importer.import_from_json = AsyncMock(return_value={
            "files_processed": 1,
            "total_processed": 5,
            "imported": 5,
            "duplicates_skipped": 0,
            "errors": 0,
            "sources": {},
            "dry_run": False,
            "start_time": "",
            "end_time": "",
        })
        mock_importer_cls.return_value = mock_importer

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(input_file), "--no-deduplicate"])

        assert result.exit_code == 0
        call_kwargs = mock_importer.import_from_json.call_args
        assert call_kwargs.kwargs["deduplicate"] is False

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_no_source_tags(self, mock_importer_cls, mock_create_storage, tmp_path):
        """--no-source-tags should pass add_source_tags=False."""
        input_file = tmp_path / "memories.json"
        input_file.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_importer = MagicMock()
        mock_importer.import_from_json = AsyncMock(return_value={
            "files_processed": 1,
            "total_processed": 5,
            "imported": 5,
            "duplicates_skipped": 0,
            "errors": 0,
            "sources": {},
            "dry_run": False,
            "start_time": "",
            "end_time": "",
        })
        mock_importer_cls.return_value = mock_importer

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(input_file), "--no-source-tags"])

        assert result.exit_code == 0
        call_kwargs = mock_importer.import_from_json.call_args
        assert call_kwargs.kwargs["add_source_tags"] is False

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_multiple_files(self, mock_importer_cls, mock_create_storage, tmp_path):
        """Multiple -i flags should pass a list of files."""
        file1 = tmp_path / "mem1.json"
        file1.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")
        file2 = tmp_path / "mem2.json"
        file2.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_importer = MagicMock()
        mock_importer.import_from_json = AsyncMock(return_value={
            "files_processed": 2,
            "total_processed": 20,
            "imported": 18,
            "duplicates_skipped": 2,
            "errors": 0,
            "sources": {},
            "dry_run": False,
            "start_time": "",
            "end_time": "",
        })
        mock_importer_cls.return_value = mock_importer

        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "-i", str(file1), "-i", str(file2),
        ])

        assert result.exit_code == 0
        call_args = mock_importer.import_from_json.call_args
        assert len(call_args.args[0]) == 2
        assert file1 in call_args.args[0]
        assert file2 in call_args.args[0]

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_db_not_found(self, mock_importer_cls, mock_create_storage, tmp_path):
        """Import should exit 1 when database file is not found."""
        input_file = tmp_path / "memories.json"
        input_file.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_create_storage.side_effect = FileNotFoundError("Database file not found")

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(input_file)])

        assert result.exit_code == 1
        assert "Error" in result.output
        mock_importer_cls.assert_not_called()

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_generic_error(self, mock_importer_cls, mock_create_storage, tmp_path):
        """Import should exit 1 on unexpected errors."""
        input_file = tmp_path / "memories.json"
        input_file.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_storage = MagicMock()
        mock_create_storage.return_value = mock_storage

        mock_importer = MagicMock()
        mock_importer.import_from_json = AsyncMock(side_effect=RuntimeError("corrupt file"))
        mock_importer_cls.return_value = mock_importer

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(input_file)])

        assert result.exit_code == 1
        assert "Error during import" in result.output

    def test_import_missing_input_file(self, tmp_path):
        """Import with non-existent input file should fail (click validation)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(tmp_path / "nonexistent.json")])
        assert result.exit_code != 0

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_requires_input(self, mock_importer_cls, mock_create_storage):
        """Import without -i should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, ["import"])
        assert result.exit_code != 0
        mock_importer_cls.assert_not_called()

    @patch("memory_os_plugins.cli.main._create_storage")
    @patch("mcp_memory_service.sync.MemoryImporter")
    def test_import_closes_storage(self, mock_importer_cls, mock_create_storage, tmp_path):
        """Import should call storage.close() in the finally block."""
        input_file = tmp_path / "memories.json"
        input_file.write_text('{"export_metadata": {}, "memories": []}', encoding="utf-8")

        mock_storage = MagicMock()
        mock_storage.close = AsyncMock()
        mock_create_storage.return_value = mock_storage

        mock_importer = MagicMock()
        mock_importer.import_from_json = AsyncMock(return_value={
            "files_processed": 1,
            "total_processed": 1,
            "imported": 1,
            "duplicates_skipped": 0,
            "errors": 0,
            "sources": {},
            "dry_run": False,
            "start_time": "",
            "end_time": "",
        })
        mock_importer_cls.return_value = mock_importer

        runner = CliRunner()
        result = runner.invoke(cli, ["import", "-i", str(input_file)])
        assert result.exit_code == 0
        mock_storage.close.assert_called_once()


# --------------------------------------------------------------------------- #
#  pull command
# --------------------------------------------------------------------------- #

class TestPullCommand:
    """Tests for the pull CLI command."""

    def test_pull_repo_not_found(self, tmp_path):
        """pull should error if repo path doesn't exist."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "enabled: true\nrepo_path: /nonexistent/path\n", encoding="utf-8"
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.load_config") as mock_load, \
             patch("memory_os_plugins.git_sync.config.CONFIG_FILE", config_path):
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path="/nonexistent/path"
            )
            result = runner.invoke(cli, ["pull"])

        assert result.exit_code == 1
        assert "Repository not found" in result.output

    def test_pull_no_memories_dir(self, tmp_path):
        """pull should report nothing to import if memories/ doesn't exist."""
        repo_path = tmp_path / "AgentMemory"
        repo_path.mkdir()
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            f"enabled: true\nrepo_path: {repo_path}\n", encoding="utf-8"
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.load_config") as mock_load, \
             patch("memory_os_plugins.git_sync.config.CONFIG_FILE", config_path):
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["pull"])

        assert result.exit_code == 0
        assert "No memories/ directory found" in result.output

    def test_pull_dry_run(self, tmp_path):
        """pull --dry-run should list memories without storing."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories" / "ab"
        memories_dir.mkdir(parents=True)
        md_content = (
            "---\n"
            "hash: abc123def456\n"
            "type: note\n"
            "tags: [test]\n"
            "created: 2026-08-03T10:00:00Z\n"
            "importance: N/A\n"
            "---\n\n"
            "Test memory content."
        )
        (memories_dir / "abc123def456.md").write_text(md_content, encoding="utf-8")

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.load_config") as mock_load, \
             patch("memory_os_plugins.git_sync.git_ops.git_pull", return_value=True):
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["pull", "--dry-run"])

        assert result.exit_code == 0
        assert "Dry-run mode" in result.output
        assert "abc123def456" in result.output

    def test_pull_imports_memories(self, tmp_path):
        """pull should import memories from Markdown files into the database."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories" / "ab"
        memories_dir.mkdir(parents=True)
        md_content = (
            "---\n"
            "hash: abc123def456\n"
            "type: note\n"
            "tags: [test]\n"
            "created: 2026-08-03T10:00:00Z\n"
            "importance: N/A\n"
            "---\n\n"
            "Test memory content."
        )
        (memories_dir / "abc123def456.md").write_text(md_content, encoding="utf-8")

        mock_storage = MagicMock()
        mock_storage.store = AsyncMock()
        mock_store_result = MagicMock()
        mock_store_result.success = True
        mock_store_result.message = "stored"
        mock_storage.store.return_value = mock_store_result

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.load_config") as mock_load, \
             patch("memory_os_plugins.git_sync.git_ops.git_pull", return_value=True), \
             patch("memory_os_plugins.cli.main._create_storage", new_callable=AsyncMock, return_value=mock_storage), \
             patch("memory_os_plugins.cli.main._close_storage", new_callable=AsyncMock):
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["pull"])

        assert result.exit_code == 0
        assert "Imported:  1" in result.output
        mock_storage.store.assert_called_once()

    def test_pull_skips_readme(self, tmp_path):
        """pull should exclude README.md from import."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories"
        memories_dir.mkdir(parents=True)
        (memories_dir / "README.md").write_text("# Memory Index\n", encoding="utf-8")

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.load_config") as mock_load, \
             patch("memory_os_plugins.git_sync.git_ops.git_pull", return_value=True):
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["pull"])

        assert result.exit_code == 0
        assert "No memory Markdown files found" in result.output


# --------------------------------------------------------------------------- #
#  switch command
# --------------------------------------------------------------------------- #

class TestSwitchCommand:
    """Tests for the switch CLI command."""

    # -- no args: display context ------------------------------------------ #

    def test_switch_no_config_shows_defaults(self, tmp_path):
        """switch with no config file should show '(none)' defaults."""
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch"])

        assert result.exit_code == 0
        assert "Current Project Context" in result.output
        assert "Project:    (none)" in result.output
        assert "User:       (none)" in result.output
        assert "Priority:   project, user" in result.output

    def test_switch_shows_current_context(self, tmp_path):
        """switch should display the current project/user from config."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "repo_path: ~/AgentMemory\n"
            "\n"
            "# Memory OS Project Scope configuration\n"
            "project_scope_current_project: my-project\n"
            "project_scope_user_name: alice\n"
            "project_scope_scope_priority: project, user\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch"])

        assert result.exit_code == 0
        assert "Current Project Context" in result.output
        assert "Project:    my-project" in result.output
        assert "User:       alice" in result.output
        assert "Priority:   project, user" in result.output

    # -- --project --------------------------------------------------------- #

    def test_switch_project_creates_config(self, tmp_path):
        """--project should create config file if it doesn't exist."""
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-p", "new-project"])

        assert result.exit_code == 0
        assert "Switched to project: new-project" in result.output
        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "project_scope_current_project: new-project" in content

    def test_switch_project_updates_config(self, tmp_path):
        """--project should update the existing config file."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "repo_path: ~/AgentMemory\n"
            "\n"
            "# Memory OS Project Scope configuration\n"
            "project_scope_current_project: old-project\n"
            "project_scope_user_name: bob\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-p", "new-project"])

        assert result.exit_code == 0
        assert "Switched to project: new-project" in result.output
        content = config_path.read_text(encoding="utf-8")
        assert "project_scope_current_project: new-project" in content
        assert "old-project" not in content
        # user_name should be preserved.
        assert "project_scope_user_name: bob" in content
        # git_sync config should be preserved.
        assert "enabled: true" in content
        assert "repo_path: ~/AgentMemory" in content

    def test_switch_project_already_on(self, tmp_path):
        """--project with same name should say 'Already on project'."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "# Memory OS Project Scope configuration\n"
            "project_scope_current_project: same-project\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-p", "same-project"])

        assert result.exit_code == 0
        assert "Already on project: same-project" in result.output

    # -- --user ------------------------------------------------------------- #

    def test_switch_user_sets_name(self, tmp_path):
        """--user should set the user name in config."""
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-u", "charlie"])

        assert result.exit_code == 0
        assert "Set user: charlie" in result.output
        content = config_path.read_text(encoding="utf-8")
        assert "project_scope_user_name: charlie" in content

    def test_switch_user_updates_existing(self, tmp_path):
        """--user should update user in existing config, preserving project."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "# Memory OS Project Scope configuration\n"
            "project_scope_current_project: my-project\n"
            "project_scope_user_name: old-user\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-u", "new-user"])

        assert result.exit_code == 0
        assert "Set user: new-user" in result.output
        content = config_path.read_text(encoding="utf-8")
        assert "project_scope_user_name: new-user" in content
        assert "project_scope_current_project: my-project" in content

    # -- --project + --user together --------------------------------------- #

    def test_switch_project_and_user_together(self, tmp_path):
        """--project and --user can be used together."""
        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-p", "proj1", "-u", "user1"])

        assert result.exit_code == 0
        assert "Switched to project: proj1" in result.output
        assert "Set user: user1" in result.output
        content = config_path.read_text(encoding="utf-8")
        assert "project_scope_current_project: proj1" in content
        assert "project_scope_user_name: user1" in content

    def test_switch_same_project_new_user(self, tmp_path):
        """Same project + new user: should say 'Already on project' but still set user."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "project_scope_current_project: same-proj\n"
            "project_scope_user_name: old-user\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-p", "same-proj", "-u", "new-user"])

        assert result.exit_code == 0
        assert "Already on project: same-proj" in result.output
        assert "Set user: new-user" in result.output
        content = config_path.read_text(encoding="utf-8")
        assert "project_scope_current_project: same-proj" in content
        assert "project_scope_user_name: new-user" in content

    # -- config preservation ----------------------------------------------- #

    def test_switch_preserves_other_plugin_config(self, tmp_path):
        """switch should preserve git_sync and r2_backup config lines."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "repo_path: ~/AgentMemory\n"
            "auto_push: false\n"
            "\n"
            "# Memory OS R2 Backup configuration\n"
            "r2_backup_enabled: false\n"
            "r2_backup_bucket_name: my-bucket\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-p", "test-project"])

        assert result.exit_code == 0
        content = config_path.read_text(encoding="utf-8")
        # Git sync config preserved.
        assert "enabled: true" in content
        assert "repo_path: ~/AgentMemory" in content
        assert "auto_push: false" in content
        # R2 backup config preserved.
        assert "r2_backup_enabled: false" in content
        assert "r2_backup_bucket_name: my-bucket" in content
        # New project scope config added.
        assert "project_scope_current_project: test-project" in content

    def test_switch_replaces_old_scope_lines(self, tmp_path):
        """switch should replace old project_scope_ lines, not duplicate."""
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "# Memory OS Project Scope configuration\n"
            "project_scope_current_project: old\n"
            "project_scope_user_name: old-user\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path):
            result = runner.invoke(cli, ["switch", "-p", "new"])

        assert result.exit_code == 0
        content = config_path.read_text(encoding="utf-8")
        # Should only have one section comment.
        assert content.count("# Memory OS Project Scope configuration") == 1
        # Old value should be gone.
        assert "project_scope_current_project: old\n" not in content
        # New value should be present.
        assert "project_scope_current_project: new" in content
        # user_name should be preserved.
        assert "project_scope_user_name: old-user" in content

    # -- --list ------------------------------------------------------------ #

    def test_switch_list_projects(self, tmp_path):
        """--list should list projects from memory file tags."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories" / "ab"
        memories_dir.mkdir(parents=True)

        md_content = (
            "---\n"
            "hash: abc123\n"
            "type: note\n"
            "tags: [proj:alpha, topic:tech]\n"
            "created: 2026-08-03T10:00:00Z\n"
            "importance: N/A\n"
            "---\n\n"
            "Memory about alpha project."
        )
        (memories_dir / "abc123.md").write_text(md_content, encoding="utf-8")

        # Second file with a different project.
        md_content2 = (
            "---\n"
            "hash: def456\n"
            "type: note\n"
            "tags: [proj:beta, topic:science]\n"
            "created: 2026-08-03T11:00:00Z\n"
            "importance: N/A\n"
            "---\n\n"
            "Memory about beta project."
        )
        (memories_dir / "def456.md").write_text(md_content2, encoding="utf-8")

        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path), \
             patch("memory_os_plugins.cli.main.load_config") as mock_load:
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["switch", "--list"])

        assert result.exit_code == 0
        assert "Known Projects" in result.output
        assert "alpha" in result.output
        assert "beta" in result.output

    def test_switch_list_projects_dedup(self, tmp_path):
        """--list should deduplicate project names."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories" / "ab"
        memories_dir.mkdir(parents=True)

        for i in range(3):
            md_content = (
                "---\n"
                f"hash: hash{i}\n"
                "type: note\n"
                "tags: [proj:same-project]\n"
                "created: 2026-08-03T10:00:00Z\n"
                "importance: N/A\n"
                "---\n\n"
                f"Memory {i}."
            )
            (memories_dir / f"hash{i}.md").write_text(md_content, encoding="utf-8")

        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path), \
             patch("memory_os_plugins.cli.main.load_config") as mock_load:
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["switch", "--list"])

        assert result.exit_code == 0
        assert "same-project" in result.output
        # Should appear only once.
        assert result.output.count("same-project") == 1

    def test_switch_list_no_memories_dir(self, tmp_path):
        """--list should say 'No projects found' if memories/ doesn't exist."""
        repo_path = tmp_path / "AgentMemory"
        repo_path.mkdir()

        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path), \
             patch("memory_os_plugins.cli.main.load_config") as mock_load:
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["switch", "--list"])

        assert result.exit_code == 0
        assert "No projects found" in result.output

    def test_switch_list_no_proj_tags(self, tmp_path):
        """--list should say 'No projects found' if no proj: tags exist."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories" / "ab"
        memories_dir.mkdir(parents=True)

        md_content = (
            "---\n"
            "hash: abc123\n"
            "type: note\n"
            "tags: [topic:tech, user:bob]\n"
            "created: 2026-08-03T10:00:00Z\n"
            "importance: N/A\n"
            "---\n\n"
            "Memory with no project tag."
        )
        (memories_dir / "abc123.md").write_text(md_content, encoding="utf-8")

        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path), \
             patch("memory_os_plugins.cli.main.load_config") as mock_load:
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["switch", "--list"])

        assert result.exit_code == 0
        assert "No projects found" in result.output

    def test_switch_list_skips_readme(self, tmp_path):
        """--list should exclude README.md from scanning."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories"
        memories_dir.mkdir(parents=True)
        (memories_dir / "README.md").write_text(
            "# Memory Index\n| tags |\n|------|\n| [proj:readme-proj] |\n",
            encoding="utf-8",
        )

        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path), \
             patch("memory_os_plugins.cli.main.load_config") as mock_load:
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["switch", "--list"])

        assert result.exit_code == 0
        assert "No projects found" in result.output

    def test_switch_list_sorted(self, tmp_path):
        """--list should output projects in sorted order."""
        repo_path = tmp_path / "AgentMemory"
        memories_dir = repo_path / "memories" / "ab"
        memories_dir.mkdir(parents=True)

        for name in ["zebra", "apple", "mango"]:
            md_content = (
                "---\n"
                f"hash: {name}\n"
                "type: note\n"
                f"tags: [proj:{name}]\n"
                "created: 2026-08-03T10:00:00Z\n"
                "importance: N/A\n"
                "---\n\n"
                f"Memory about {name}."
            )
            (memories_dir / f"{name}.md").write_text(md_content, encoding="utf-8")

        config_path = tmp_path / "config.yml"

        runner = CliRunner()
        with patch("memory_os_plugins.cli.main.CONFIG_FILE", config_path), \
             patch("memory_os_plugins.cli.main.load_config") as mock_load:
            from memory_os_plugins.git_sync.config import GitSyncConfig
            mock_load.return_value = GitSyncConfig(
                enabled=True, repo_path=str(repo_path)
            )
            result = runner.invoke(cli, ["switch", "--list"])

        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        project_lines = [l.strip() for l in lines if l.strip() and not l.startswith("=") and not l.startswith("Known")]
        assert project_lines == ["apple", "mango", "zebra"]


# --------------------------------------------------------------------------- #
#  main() entry point
# --------------------------------------------------------------------------- #

class TestMainEntryPoint:
    def test_main_calls_cli(self):
        """main() should be callable and delegate to click group."""
        from memory_os_plugins.cli.main import main

        with patch("memory_os_plugins.cli.main.cli") as mock_cli:
            main()
            mock_cli.assert_called_once()
