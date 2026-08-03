from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any

from .exporters import ExportedPackage, materialize_exported_package


@dataclass(slots=True)
class ValidationCheck:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PackageValidationResult:
    target: str
    status: str
    checks: list[ValidationCheck]
    command: list[str] | None = None
    stdout: str = ""
    stderr: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "status": self.status,
            "checks": [item.as_dict() for item in self.checks],
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _expected_paths(package: ExportedPackage) -> set[str]:
    return {item.path for item in package.files}


def _structural_checks(package: ExportedPackage) -> list[ValidationCheck]:
    paths = _expected_paths(package)
    checks = [
        ValidationCheck(
            name="files_present",
            status="passed" if package.files else "failed",
            detail=f"{len(package.files)} file(s) exported",
        )
    ]
    if package.target == "dbt":
        required = {"dbt_project.yml", "profiles.example.yml", "README.md"}
        required_present = required.issubset(paths) and any(path.startswith("models/") for path in paths)
        checks.append(
            ValidationCheck(
                name="dbt_scaffold",
                status="passed" if required_present else "failed",
                detail="dbt scaffold files are present"
                if required_present
                else "Missing dbt project scaffold files",
            )
        )
    elif package.target == "dataform":
        required = {"workflow_settings.yaml", "README.md"}
        required_present = required.issubset(paths) and any(path.startswith("definitions/") for path in paths)
        checks.append(
            ValidationCheck(
                name="dataform_scaffold",
                status="passed" if required_present else "failed",
                detail="Dataform scaffold files are present"
                if required_present
                else "Missing Dataform scaffold files",
            )
        )
    elif package.target == "postgres_view":
        checks.append(
            ValidationCheck(
                name="postgres_sql_present",
                status="passed" if any(path.endswith(".sql") for path in paths) else "failed",
                detail="Deployable SQL file is present"
                if any(path.endswith(".sql") for path in paths)
                else "Missing PostgreSQL SQL file",
            )
        )
    return checks


def _status_from_checks(checks: list[ValidationCheck]) -> str:
    if any(item.status == "failed" for item in checks):
        return "failed"
    if any(item.status == "partial" for item in checks):
        return "partial"
    return "passed"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolve_cli_path(
    *,
    env_var: str,
    executable_name: str,
    fallback_paths: list[Path],
) -> str | None:
    explicit = os.getenv(env_var)
    if explicit:
        path = Path(explicit)
        if path.exists():
            return str(path)
    discovered = shutil.which(executable_name)
    if discovered:
        return discovered
    for candidate in fallback_paths:
        if candidate.exists():
            return str(candidate)
    return None


def _run_dbt_cli(project_root: Path) -> tuple[list[str], str, str, str]:
    command = _resolve_cli_path(
        env_var="DBT_CLI_PATH",
        executable_name="dbt",
        fallback_paths=[
            _repo_root() / ".tools" / "dbt-venv" / "Scripts" / "dbt.exe",
            _repo_root() / ".tools" / "dbt-venv" / "bin" / "dbt",
        ],
    )
    if not command:
        return [], "", "", "dbt CLI is not installed"
    profiles_dir = project_root / ".profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_source = project_root / "profiles.example.yml"
    if profile_source.exists():
        (profiles_dir / "profiles.yml").write_text(profile_source.read_text(encoding="utf-8"), encoding="utf-8")
    cmd = [
        command,
        "parse",
        "--project-dir",
        str(project_root),
        "--profiles-dir",
        str(profiles_dir),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=project_root)
    status = "passed" if completed.returncode == 0 else "failed"
    return cmd, completed.stdout, completed.stderr, status


def _run_dataform_cli(project_root: Path) -> tuple[list[str], str, str, str]:
    command = _resolve_cli_path(
        env_var="DATAFORM_CLI_PATH",
        executable_name="dataform",
        fallback_paths=[
            _repo_root() / ".tools" / "dataform-cli" / "node_modules" / ".bin" / "dataform.cmd",
            _repo_root() / ".tools" / "dataform-cli" / "node_modules" / ".bin" / "dataform",
        ],
    )
    if not command:
        return [], "", "", "dataform CLI is not installed"
    cmd = [command, "compile"]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=project_root)
    status = "passed" if completed.returncode == 0 else "failed"
    return cmd, completed.stdout, completed.stderr, status


def validate_exported_package(package: ExportedPackage) -> PackageValidationResult:
    checks = _structural_checks(package)
    if _status_from_checks(checks) == "failed":
        return PackageValidationResult(target=package.target, status="failed", checks=checks)
    if package.target == "postgres_view":
        checks.append(
            ValidationCheck(
                name="cli_validation",
                status="partial",
                detail="No CLI validation step is defined for raw PostgreSQL bundles",
            )
        )
        return PackageValidationResult(target=package.target, status="partial", checks=checks)
    with tempfile.TemporaryDirectory(prefix=f"datapilot-{package.target}-") as temp_dir:
        project_root = materialize_exported_package(package, Path(temp_dir))
        if package.target == "dbt":
            command, stdout, stderr, cli_status = _run_dbt_cli(project_root)
        else:
            command, stdout, stderr, cli_status = _run_dataform_cli(project_root)
    if cli_status == "passed":
        checks.append(
            ValidationCheck(
                name="cli_validation",
                status="passed",
                detail=f"{package.target} CLI validation passed",
            )
        )
        final_status = "passed"
    elif cli_status == "failed":
        checks.append(
            ValidationCheck(
                name="cli_validation",
                status="failed",
                detail=f"{package.target} CLI validation failed",
            )
        )
        final_status = "failed"
    else:
        checks.append(
            ValidationCheck(
                name="cli_validation",
                status="partial",
                detail=cli_status,
            )
        )
        final_status = "partial"
    return PackageValidationResult(
        target=package.target,
        status=final_status,
        checks=checks,
        command=command or None,
        stdout=stdout,
        stderr=stderr,
    )
