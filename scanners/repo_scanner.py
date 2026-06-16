import json
import logging
import os
import re
from typing import Any

from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".turbo",
    "coverage",
    ".tox",
    ".eggs",
}

PACKAGE_MANAGER_FILES: dict[str, str] = {
    "requirements.txt": "pip",
    "requirements.in": "pip-tools",
    "Pipfile": "pipenv",
    "pyproject.toml": "pip/poetry/hatch",
    "setup.py": "pip-setup",
    "setup.cfg": "pip-setup",
    "package.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "Cargo.toml": "cargo",
    "go.mod": "go-modules",
    "composer.json": "composer",
    "Gemfile": "bundler",
    "mix.exs": "elixir-mix",
    "build.gradle": "gradle",
    "pom.xml": "maven",
    "deno.json": "deno",
    "deno.jsonc": "deno",
}

FRAMEWORK_FILES: dict[str, str] = {
    "manage.py": "django",
    "next.config.js": "nextjs",
    "next.config.mjs": "nextjs",
    "next.config.ts": "nextjs",
    "nuxt.config.js": "nuxtjs",
    "nuxt.config.ts": "nuxtjs",
    "vite.config.js": "vite",
    "vite.config.ts": "vite",
    "angular.json": "angular",
    "svelte.config.js": "svelte",
    "gatsby-config.js": "gatsby",
    "remix.config.js": "remix",
    "astro.config.mjs": "astro",
    "astro.config.ts": "astro",
    "vue.config.js": "vuejs",
}

DOCKER_FILES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "docker-compose.yml": "compose",
    "docker-compose.yaml": "compose",
    "docker-compose.override.yml": "compose-override",
    ".dockerignore": "dockerignore",
}

CI_CD_INDICATORS: dict[str, str] = {
    ".github/workflows": "github-actions",
    ".gitlab-ci.yml": "gitlab-ci",
    "Jenkinsfile": "jenkins",
    ".circleci": "circleci",
    ".travis.yml": "travis-ci",
    "bitbucket-pipelines.yml": "bitbucket-pipelines",
    ".drone.yml": "drone-ci",
    "fly.toml": "fly.io",
    "render.yaml": "render",
    "vercel.json": "vercel",
    "netlify.toml": "netlify",
    "cloudbuild.yaml": "google-cloud-build",
}

AI_CONFIG_FILES: dict[str, str] = {
    "mcp.json": "mcp",
    ".mcp.json": "mcp",
    "mcp_server.py": "mcp-server",
    "CLAUDE.md": "claude",
    ".claude": "claude-config",
    "n8n-workflow.json": "n8n",
    ".n8n": "n8n",
    ".cursor": "cursor",
    ".cursorrules": "cursor",
}

PROCESS_MANAGER_FILES: dict[str, str] = {
    "ecosystem.config.js": "pm2",
    "pm2.config.js": "pm2",
    "Procfile": "procfile",
    "supervisord.conf": "supervisord",
    "supervisor.conf": "supervisord",
    "uwsgi.ini": "uwsgi",
    "gunicorn.conf.py": "gunicorn",
}

PYTHON_AI_PACKAGES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google-generativeai": "gemini",
    "google-genai": "gemini",
    "ollama": "ollama",
    "langchain": "langchain",
    "langchain-openai": "langchain",
    "langchain-anthropic": "langchain",
    "langchain-core": "langchain",
    "langchain-community": "langchain",
    "litellm": "litellm",
    "tiktoken": "openai-tokenizer",
    "transformers": "huggingface",
    "sentence-transformers": "embeddings",
    "chromadb": "vector-db-chroma",
    "pinecone-client": "vector-db-pinecone",
    "weaviate-client": "vector-db-weaviate",
    "qdrant-client": "vector-db-qdrant",
    "llama-index": "llama-index",
    "llama_index": "llama-index",
    "cohere": "cohere",
    "mistralai": "mistral",
    "together": "together-ai",
    "groq": "groq",
    "instructor": "instructor",
    "dspy-ai": "dspy",
    "crewai": "crewai",
    "pyautogen": "autogen",
}

NPM_AI_PACKAGES: dict[str, str] = {
    "openai": "openai",
    "@anthropic-ai/sdk": "anthropic",
    "anthropic": "anthropic",
    "langchain": "langchain",
    "@langchain/core": "langchain",
    "@langchain/openai": "langchain",
    "@langchain/anthropic": "langchain",
    "ollama": "ollama",
    "groq-sdk": "groq",
    "@google/generative-ai": "gemini",
    "cohere-ai": "cohere",
    "mistralai": "mistral",
    "ai": "vercel-ai-sdk",
    "@ai-sdk/openai": "vercel-ai-sdk",
    "@ai-sdk/anthropic": "vercel-ai-sdk",
    "@modelcontextprotocol/sdk": "mcp",
    "llamaindex": "llama-index",
}

LANGUAGE_EXT: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".ex": "elixir",
    ".exs": "elixir",
    ".scala": "scala",
    ".swift": "swift",
    ".sh": "shell",
}


class RepoScanner(BaseScanner):
    """Scans a local repository for structural and technological intelligence.

    Detects: languages, package managers, frameworks, Docker, CI/CD, AI SDKs,
    MCP usage, process managers, env files, and cron indicators.

    Rule-based detection only. Read-only. Does not modify files.
    """

    name = "repo_scanner"

    def _scan(self, target: str) -> dict[str, Any]:
        if not os.path.isdir(target):
            logger.warning("Target is not a directory", extra={"target": target})
            return {"error": "target_not_found", "target": target}

        abs_target = os.path.abspath(target)
        all_files: list[str] = []
        ext_counts: dict[str, int] = {}

        for root, dirs, files in os.walk(abs_target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]
            for fname in files:
                rel = os.path.relpath(os.path.join(root, fname), abs_target)
                all_files.append(rel)
                ext = os.path.splitext(fname)[1].lower()
                if ext:
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1

        result: dict[str, Any] = {
            "target": abs_target,
            "name": os.path.basename(abs_target),
            "total_files": len(all_files),
            "languages": ext_counts,
            "primary_language": _primary_language(ext_counts),
            "has_git": os.path.isdir(os.path.join(abs_target, ".git")),
            "git_branch": _git_branch(abs_target),
            "package_managers": _detect_by_file_map(abs_target, PACKAGE_MANAGER_FILES),
            "frameworks": _detect_frameworks(abs_target),
            "docker": _detect_docker(abs_target),
            "ci_cd": _detect_by_file_map(abs_target, CI_CD_INDICATORS),
            "env_files": _detect_env_files(abs_target),
            "process_managers": _detect_by_file_map(abs_target, PROCESS_MANAGER_FILES),
            "ai_config_files": _detect_by_file_map(abs_target, AI_CONFIG_FILES),
            "llm_sdks": _detect_llm_sdks(abs_target),
            "capabilities": _infer_capabilities(abs_target, all_files, ext_counts),
        }

        logger.info(
            "Repo scan complete",
            extra={
                "target": abs_target,
                "repo_name": result["name"],
                "total_files": result["total_files"],
                "primary_language": result["primary_language"],
                "frameworks": result["frameworks"],
                "llm_sdks": result["llm_sdks"],
            },
        )
        return result


def _primary_language(ext_counts: dict[str, int]) -> str:
    best_ext, best_count = "", 0
    for ext, count in ext_counts.items():
        if ext in LANGUAGE_EXT and count > best_count:
            best_count = count
            best_ext = ext
    return LANGUAGE_EXT.get(best_ext, "unknown")


def _detect_by_file_map(target: str, file_map: dict[str, str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for fname, label in file_map.items():
        if label not in seen and os.path.exists(os.path.join(target, fname)):
            found.append(label)
            seen.add(label)
    return found


def _detect_docker(target: str) -> dict[str, Any]:
    indicators = _detect_by_file_map(target, DOCKER_FILES)
    return {"present": bool(indicators), "indicators": indicators}


def _detect_env_files(target: str) -> list[str]:
    candidates = [
        ".env",
        ".env.example",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
    ]
    return [f for f in candidates if os.path.isfile(os.path.join(target, f))]


def _git_branch(target: str) -> str | None:
    head = os.path.join(target, ".git", "HEAD")
    if not os.path.isfile(head):
        return None
    try:
        content = open(head).read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/") :]
        return content[:8]  # detached HEAD
    except OSError:
        return None


def _detect_frameworks(target: str) -> list[str]:
    found = set(_detect_by_file_map(target, FRAMEWORK_FILES))

    python_pkgs = _python_package_names(target)
    for pkg, label in [
        ("fastapi", "fastapi"),
        ("flask", "flask"),
        ("django", "django"),
        ("uvicorn", "uvicorn"),
        ("starlette", "starlette"),
        ("aiohttp", "aiohttp"),
        ("tornado", "tornado"),
        ("sanic", "sanic"),
    ]:
        if pkg in python_pkgs:
            found.add(label)

    npm_pkgs = _npm_package_names(target)
    for pkg, label in [
        ("react", "react"),
        ("react-dom", "react"),
        ("vue", "vue"),
        ("express", "express"),
        ("fastify", "fastify"),
        ("@nestjs/core", "nestjs"),
        ("hono", "hono"),
    ]:
        if pkg in npm_pkgs:
            found.add(label)

    return sorted(found)


def _detect_llm_sdks(target: str) -> list[str]:
    found: set[str] = set()

    python_pkgs = _python_package_names(target)
    for pkg, sdk in PYTHON_AI_PACKAGES.items():
        if pkg in python_pkgs:
            found.add(sdk)

    npm_pkgs = _npm_package_names(target)
    for pkg, sdk in NPM_AI_PACKAGES.items():
        if pkg in npm_pkgs:
            found.add(sdk)

    return sorted(found)


def _python_package_names(target: str) -> set[str]:
    packages: set[str] = set()

    req = os.path.join(target, "requirements.txt")
    if os.path.isfile(req):
        try:
            for line in open(req):
                line = line.strip()
                if line and not line.startswith("#"):
                    pkg = re.split(r"[>=<!;\[ ]", line)[0].strip().lower()
                    if pkg:
                        packages.add(pkg)
        except OSError:
            pass

    pyproject = os.path.join(target, "pyproject.toml")
    if os.path.isfile(pyproject):
        try:
            content = open(pyproject).read()
            for m in re.finditer(r'"([a-zA-Z0-9][a-zA-Z0-9_\-]*)\s*[>=<!,\[]', content):
                packages.add(m.group(1).lower().replace("_", "-"))
        except OSError:
            pass

    return packages


def _npm_package_names(target: str) -> set[str]:
    packages: set[str] = set()
    pkg_json = os.path.join(target, "package.json")
    if not os.path.isfile(pkg_json):
        return packages
    try:
        data = json.loads(open(pkg_json).read())
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(data.get(section), dict):
                packages.update(data[section].keys())
    except (OSError, json.JSONDecodeError):
        pass
    return packages


def _infer_capabilities(
    target: str, all_files: list[str], ext_counts: dict[str, int]
) -> dict[str, bool]:
    entry_points = {"main.py", "app.py", "server.py", "index.js", "index.ts", "main.ts"}
    return {
        "web_api": any(f in all_files or os.path.basename(f) in entry_points for f in all_files),
        "has_database": (
            ext_counts.get(".db", 0) > 0
            or ext_counts.get(".sqlite", 0) > 0
            or any(f in all_files for f in ["models.py", "database.py", "db.py"])
        ),
        "has_tests": (
            os.path.isdir(os.path.join(target, "tests"))
            or os.path.isdir(os.path.join(target, "test"))
            or any(os.path.basename(f).startswith("test_") for f in all_files)
        ),
        "has_scripts": (
            os.path.isdir(os.path.join(target, "scripts")) or ext_counts.get(".sh", 0) > 0
        ),
        "is_library": any(f in all_files for f in ["setup.py", "pyproject.toml"]),
    }
