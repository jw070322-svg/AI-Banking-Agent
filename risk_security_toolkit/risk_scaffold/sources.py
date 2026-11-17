"""Read bounded UTF-8 documentation without importing repository code."""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SourceError(RuntimeError):
    """A safe, actionable ingestion error without response bodies or credentials."""


@dataclass(frozen=True)
class Limits:
    max_files: int = 250
    max_file_bytes: int = 512_000
    max_total_bytes: int = 8_000_000

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("All ingestion limits must be positive integers")


@dataclass(frozen=True)
class Document:
    path: str
    text: str
    sha256: str
    source: str


@dataclass
class Corpus:
    repository: str
    revision: str
    documents: list[Document] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Source(Protocol):
    def collect(self, limits: Limits) -> Corpus: ...


EXCLUDED = {".git", ".hg", ".svn", "node_modules", "vendor", "__pycache__",
            "venv", ".venv", "build", "dist", "output", "generated"}
EXTENSIONS = {".md", ".markdown", ".rst", ".txt", ".py"}


def safe_path(path: str) -> bool:
    # Reject Windows drive/ADS paths as well as POSIX traversal.
    return (bool(path) and not path.startswith("/") and "\\" not in path
            and ":" not in path and all(p not in {"", ".", ".."} for p in path.split("/")))


def candidate(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (safe_path(path) and not any(p.startswith(".") or p.casefold() in EXCLUDED
                                      for p in parts)
            and (PurePosixPath(path).suffix.casefold() in EXTENSIONS
                 or PurePosixPath(path).name.upper() in {"README", "SECURITY"}))


def add_document(corpus: Corpus, path: str, raw: bytes, source: str, limits: Limits):
    if len(raw) > limits.max_file_bytes:
        corpus.warnings.append(f"Skipped oversized document: {path}")
        return
    if len(corpus.documents) >= limits.max_files:
        raise SourceError("Document limit reached; narrow the source or raise --max-files")
    total = sum(len(d.text.encode("utf-8")) for d in corpus.documents)
    if total + len(raw) > limits.max_total_bytes:
        raise SourceError("Total documentation byte limit reached")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        corpus.warnings.append(f"Skipped non-UTF-8 document: {path}")
        return
    if "\x00" in text:
        corpus.warnings.append(f"Skipped binary document: {path}")
        return
    corpus.documents.append(Document(path, text, hashlib.sha256(raw).hexdigest(), source))


class LocalSource:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise SourceError("Local source must be a directory")

    def collect(self, limits: Limits) -> Corpus:
        # Local trees may contain uncommitted edits; hashes identify actual input.
        corpus = Corpus(str(self.root), "working-tree")
        for directory, names, files in os.walk(self.root, followlinks=False):
            names[:] = sorted(n for n in names if not n.startswith(".")
                              and n.casefold() not in EXCLUDED
                              and not (Path(directory) / n).is_symlink()
                              and not getattr(Path(directory) / n, "is_junction", lambda: False)())
            for name in sorted(files):
                file = Path(directory) / name
                path = file.relative_to(self.root).as_posix()
                if file.suffix.casefold() == ".pdf":
                    corpus.warnings.append(f"Unsupported PDF (extract separately): {path}")
                if not candidate(path):
                    continue
                if file.is_symlink() or not file.resolve().is_relative_to(self.root):
                    corpus.warnings.append(f"Skipped link or external path: {path}")
                    continue
                with file.open("rb") as stream:
                    raw = stream.read(limits.max_file_bytes + 1)
                add_document(corpus, path, raw, path, limits)
        return corpus


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A repository rename must never forward a credential to another URL.
        return None


class GitHubTransport:
    """GitHub.com only; bounded GETs, TLS validation, timeout, no redirects."""

    def __init__(self, token: str | None = None, timeout: float = 20):
        if token and any(c in token for c in "\r\n"):
            raise ValueError("Invalid GitHub token")
        self._token = token
        self.timeout = timeout
        self._opener = build_opener(NoRedirects())

    def get_json(self, path: str, max_bytes: int = 12_000_000):
        if not path.startswith("/repos/") or "\\" in path:
            raise SourceError("Only repository endpoints are allowed")
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2026-03-10",
                   "User-Agent": "github-risk-scaffold/0.1"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = Request("https://api.github.com" + path, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise SourceError("GitHub response exceeds the configured size limit")
            return json.loads(raw)
        except HTTPError as exc:
            if exc.code in {403, 429}:
                reset = exc.headers.get("X-RateLimit-Reset", "unknown")
                retry = exc.headers.get("Retry-After", "unknown")
                raise SourceError(f"GitHub denied/rate-limited read ({exc.code}); "
                                  f"check Contents:read, Retry-After={retry}, reset={reset}") from None
            messages = {401: "check GITHUB_TOKEN", 404: "check repository, ref and access",
                        409: "repository may be empty", 301: "use the canonical repository name",
                        302: "redirect rejected"}
            raise SourceError(f"GitHub HTTP {exc.code}: "
                              + messages.get(exc.code, "retry the read later")) from None
        except (URLError, TimeoutError, OSError):
            raise SourceError("GitHub network/TLS failure; check connectivity and retry") from None
        except (ValueError, UnicodeDecodeError):
            raise SourceError("GitHub returned invalid JSON") from None


def repository_name(value: str) -> str:
    if value.startswith("https://"):
        url = urlsplit(value)
        if (url.netloc != "github.com" or url.query or url.fragment
                or url.username or url.password):
            raise ValueError("Use an https://github.com/owner/repo URL")
        value = url.path.strip("/")
    value = value.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value):
        raise ValueError("Repository must be owner/repo or its GitHub.com HTTPS URL")
    if value.split("/")[1] in {".", ".."}:
        raise ValueError("Invalid repository name")
    return value


class GitHubSource:
    def __init__(self, repository: str, ref: str | None = None, transport=None):
        self.repository = repository_name(repository)
        self.ref = ref
        self.transport = transport or GitHubTransport(os.environ.get("GITHUB_TOKEN"))

    def collect(self, limits: Limits) -> Corpus:
        base = "/repos/" + self.repository
        get = self.transport.get_json
        ref = self.ref or get(base)["default_branch"]
        # Resolve a moving ref once; every subsequent read uses the same commit.
        commit = get(base + "/commits/" + quote(ref, safe=""))
        sha = commit["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise SourceError("Invalid commit SHA in GitHub response")
        corpus = Corpus(self.repository, sha)
        tree = get(base + "/git/trees/" + sha + "?recursive=1")
        if tree.get("truncated"):
            raise SourceError("GitHub tree is truncated; use a local clone or narrower repository")
        entries = sorted(tree["tree"], key=lambda e: e["path"])
        for entry in entries:
            path = entry["path"]
            if PurePosixPath(path).suffix.casefold() == ".pdf":
                corpus.warnings.append(f"Unsupported PDF (extract separately): {path}")
            if entry.get("type") != "blob" or not candidate(path):
                continue
            if entry.get("mode") not in {"100644", "100755"}:
                corpus.warnings.append(f"Skipped non-regular Git object: {path}")
                continue
            if entry.get("size", 0) > limits.max_file_bytes:
                corpus.warnings.append(f"Skipped oversized document: {path}")
                continue
            if len(corpus.documents) >= limits.max_files:
                raise SourceError("Document limit reached; narrow the source or raise --max-files")
            item = get(base + "/contents/" + quote(path, safe="/") + "?ref=" + sha)
            if item.get("type") != "file" or item.get("encoding") != "base64":
                raise SourceError(f"Expected a Base64 regular file: {path}")
            if item.get("sha") != entry.get("sha"):
                raise SourceError(f"Content identity changed unexpectedly: {path}")
            try:
                raw = base64.b64decode("".join(item["content"].split()), validate=True)
            except (binascii.Error, KeyError, ValueError):
                raise SourceError(f"Invalid Base64 document: {path}") from None
            blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if blob_sha != entry["sha"]:
                raise SourceError(f"Git blob integrity check failed: {path}")
            source = f"https://github.com/{self.repository}/blob/{sha}/{quote(path, safe='/')}"
            add_document(corpus, path, raw, source, limits)
        return corpus


class SnapshotSource:
    """Read a local export from an authorized connector, with content hashes.

    Hashes detect accidental changes; an unsigned export does not authenticate
    GitHub. Create exports only from a trusted, authorized read of the repository.
    """

    def __init__(self, path: Path):
        self.path = path

    def collect(self, limits: Limits) -> Corpus:
        with self.path.open("rb") as stream:
            raw = stream.read(limits.max_total_bytes * 2 + 1)
        if len(raw) > limits.max_total_bytes * 2:
            raise SourceError("Snapshot exceeds the configured size limit")
        data = json.loads(raw)
        repository = repository_name(data["repository"])
        revision = data["revision"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise SourceError("Snapshot needs an immutable commit SHA")
        corpus = Corpus(repository, revision)
        corpus.warnings.append("Unsigned connector export: verify provenance before trusting its origin")
        for warning in data.get("warnings", []):
            if not isinstance(warning, str):
                raise SourceError("Snapshot warnings must be strings")
            corpus.warnings.append(warning)
        seen = set()
        for item in data["documents"]:
            path = item["path"]
            if not candidate(path) or path in seen:
                raise SourceError("Snapshot contains an unsupported or duplicate document path")
            seen.add(path)
            content = item["text"].encode("utf-8")
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise SourceError(f"Snapshot content hash mismatch: {path}")
            source = f"https://github.com/{repository}/blob/{revision}/{quote(path, safe='/')}"
            add_document(corpus, path, content, source, limits)
        return corpus
