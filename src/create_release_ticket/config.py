"""Configuration management using Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JiraConfig(BaseModel):
    """Jira configuration."""

    base_url: str = "https://netskope.atlassian.net"
    project_id: str = "10011"
    promote_issue_type_id: str = "7"
    deployment_issue_type_id: str = "10940"
    component_id: str = "13002"
    component_name: str = "Query Service (QS)"
    user_id: str = ""  # Set via JIRA_USER_ID env var
    done_transition_id: str = "761"


class GitHubConfig(BaseModel):
    """GitHub configuration."""

    owner: str = "netSkope"
    repo: str = "query-engine"
    workflow_file: str = "ep-falcon-distribution.yml"
    notify_emails: str = ""  # Set via GITHUB_NOTIFY_EMAILS env var (optional)
    destinations: str = "commercial:pre-prod commercial:prod"
    manifest_service: str = "queryservice"


class JenkinsConfig(BaseModel):
    """Jenkins configuration."""

    job_name: str = "one_button_queryservice"
    regions: str = "America"
    pop_types: str = "MP"
    pops: str = "devint-automation-iad0-nc1"
    slack_channel: str = "#queryservice-deployments,#eng-deployments,#deployments"
    stork_component_name: str = "queryservice"
    run_qe_pdv: str = "DEPLOY_AND_PDV"
    pdv_config_image_tag: str = "2.0.121"
    poll_interval_seconds: int = 30
    timeout_minutes: int = 60
    max_consecutive_poll_failures: int = 5


class RetryConfig(BaseModel):
    """Retry configuration."""

    max_attempts: int = 3
    backoff_seconds: int = 2


class AppConfig(BaseModel):
    """Application configuration from config.yaml."""

    jira: JiraConfig = Field(default_factory=JiraConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    jenkins: JenkinsConfig = Field(default_factory=JenkinsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    timezone: str = "+08:00"


class Settings(BaseSettings):
    """Environment settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Jira credentials
    jira_email: str = Field(..., description="Jira email address")
    jira_api_token: str = Field(..., description="Jira API token")
    jira_user_id: str = Field(..., description="Jira account ID (from /rest/api/3/myself)")

    # GitHub credentials
    github_pat: str = Field(..., description="GitHub Personal Access Token")

    # Jenkins credentials
    jenkins_url: str = Field(..., description="Jenkins base URL")
    jenkins_user: str = Field(..., description="Jenkins username")
    jenkins_api_token: str = Field(..., description="Jenkins API token")

    # Optional overrides
    github_notify_emails: str = Field(default="", description="Space-separated notification emails")


def load_app_config(config_path: Path | None = None) -> AppConfig:
    """Load application configuration from YAML file."""
    if config_path is None:
        # Try to find config.yaml in current directory or project root
        possible_paths = [
            Path.cwd() / "config.yaml",
            Path(__file__).parent.parent.parent.parent / "config.yaml",
        ]
        for path in possible_paths:
            if path.exists():
                config_path = path
                break

    if config_path and config_path.exists():
        with open(config_path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return AppConfig(**data)

    return AppConfig()


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    """Get cached app config instance, with personal env overrides applied."""
    config = load_app_config()
    settings = get_settings()

    jira_override: dict[str, Any] = {}
    if settings.jira_user_id:
        jira_override["user_id"] = settings.jira_user_id

    github_override: dict[str, Any] = {}
    if settings.github_notify_emails:
        github_override["notify_emails"] = settings.github_notify_emails

    if not jira_override and not github_override:
        return config

    return config.model_copy(
        update={
            "jira": config.jira.model_copy(update=jira_override),
            "github": config.github.model_copy(update=github_override),
        }
    )
