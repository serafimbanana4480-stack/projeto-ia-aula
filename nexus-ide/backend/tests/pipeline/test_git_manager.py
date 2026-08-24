"""Tests for GitManager."""
import subprocess
from pathlib import Path

import pytest

from backend.pipeline.git_manager import ConventionalCommit, GitError, GitManager


@pytest.fixture
def empty_repo(tmp_path: Path) -> GitManager:
    repo = tmp_path / "repo"
    repo.mkdir()
    gm = GitManager(repo)
    gm.init_repo()
    return gm


class TestGitManagerInit:
    def test_init_creates_git_dir(self, tmp_path: Path) -> None:
        repo = tmp_path / "newrepo"
        gm = GitManager(repo)
        gm.init_repo()
        assert (repo / ".git").is_dir()

    def test_init_idempotent(self, empty_repo: GitManager) -> None:
        # Should not error on second init
        empty_repo.init_repo(initial_commit=False)
        assert (empty_repo.repo_path / ".git").is_dir()

    def test_initial_commit_created(self, empty_repo: GitManager) -> None:
        log = empty_repo.log_summary(n=1)
        assert len(log) == 1
        assert "initial commit" in log[0]["subject"].lower()


class TestGitBranches:
    def test_create_feature_branch(self, empty_repo: GitManager) -> None:
        branch = empty_repo.create_feature_branch("story-abc12345", "Add user API")
        assert branch.startswith("feature/story-abc12345-add-user-api")
        assert empty_repo.current_branch() == branch

    def test_branch_sanitization(self, empty_repo: GitManager) -> None:
        branch = empty_repo.create_feature_branch("story-1", "Fix & Update!!!")
        # Should contain only safe characters
        assert "&" not in branch
        assert "!" not in branch

    def test_checkout(self, empty_repo: GitManager) -> None:
        empty_repo.create_feature_branch("story-1", "feat1")
        empty_repo._run(["checkout", "master"], check=False)
        empty_repo._run(["checkout", "main"], check=False)


class TestGitCommits:
    def test_commit_files(self, empty_repo: GitManager) -> None:
        # Create a file and commit
        file_path = empty_repo.repo_path / "app.py"
        file_path.write_text("x = 1")

        hash_ = empty_repo.commit_files(["app.py"], "feat(app): add variable", story_id="story-1")
        assert len(hash_) == 40  # SHA-1 length
        assert not empty_repo.has_uncommitted_changes()

    def test_commit_message_includes_story(self, empty_repo: GitManager) -> None:
        file_path = empty_repo.repo_path / "mod.py"
        file_path.write_text("pass")
        empty_repo.commit_files(["mod.py"], "feat: new module", story_id="story-xyz")

        # Check full commit message body includes story ID
        result = empty_repo._run(["log", "-1", "--format=%B"], check=False)
        assert "story-xyz" in result.stdout

    def test_has_uncommitted_changes_true(self, empty_repo: GitManager) -> None:
        (empty_repo.repo_path / "dirty.py").write_text("dirty")
        assert empty_repo.has_uncommitted_changes()

    def test_has_uncommitted_changes_false(self, empty_repo: GitManager) -> None:
        assert not empty_repo.has_uncommitted_changes()


class TestConventionalCommit:
    def test_parse_standard(self) -> None:
        gm = GitManager(Path("."))
        commit = gm._parse_commit_message("feat(api): add user endpoints")
        assert commit.type_ == "feat"
        assert commit.scope == "api"
        assert commit.description == "add user endpoints"
        assert not commit.breaking

    def test_parse_breaking(self) -> None:
        gm = GitManager(Path("."))
        commit = gm._parse_commit_message("feat(api)!: remove legacy endpoints")
        assert commit.breaking

    def test_parse_no_scope(self) -> None:
        gm = GitManager(Path("."))
        commit = gm._parse_commit_message("docs: update README")
        assert commit.type_ == "docs"
        assert commit.scope == ""

    def test_format(self) -> None:
        cc = ConventionalCommit(type_="feat", scope="auth", description="login", body="Story-1")
        text = cc.format()
        assert text.startswith("feat(auth): login")
        assert "Story-1" in text


class TestGitErrors:
    def test_invalid_command_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # GIT_CEILING_DIRECTORIES impede o git de descobrir o repo pai
        # (o basetemp vive dentro do proprio repo nexus-ide).
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        repo = tmp_path / "not-a-repo"
        repo.mkdir()
        gm = GitManager(repo)
        with pytest.raises(GitError):
            gm._run(["status"], check=True)
