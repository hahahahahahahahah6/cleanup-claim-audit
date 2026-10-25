"""Core audit logic: docs temp-file cleanup claims vs Python source evidence."""

import ast
import fnmatch
import json
import re
from pathlib import Path

VERSION = "0.1.0"

# Longest first so a longer phrase wins when both match one sentence;
# families collapse matches anyway, order only affects reported phrases.
CLEANUP_PHRASES = [
    "automatically cleans up temporary files",
    "automatic cleanup of temporary files",
    "cleans up temporary files",
    "clean up temporary files",
    "cleans up its temporary files",
    "cleans up temp files",
    "clean up temp files",
    "removes temporary files",
    "remove temporary files",
    "removes temp files",
    "remove temp files",
    "temporary files are cleaned up",
    "temp files are cleaned up",
    "temporary files are removed",
    "temp files are removed",
    "no temporary files left behind",
    "leaves no temporary files",
    "cleans up after itself",
    "clean up after itself",
    "temporary files cleaned up",
    "temp files cleaned up",
]

NOCLEANUP_PHRASES = [
    "does not clean up temporary files",
    "does not clean up temp files",
    "never cleans up temporary files",
    "does not remove temporary files",
    "leaves temporary files behind",
    "temporary files are left behind",
    "no cleanup of temporary files",
    "does not clean up after itself",
]

CLEANUP = "cleanup"
NOCLEANUP = "nocleanup"

PHRASE_FAMILIES = (
    [(p, CLEANUP) for p in CLEANUP_PHRASES]
    + [(p, NOCLEANUP) for p in NOCLEANUP_PHRASES]
)

NEGATIONS = {"no", "not", "never", "without"}
CLEANUP_CALL_ATTRS = {"unlink", "remove", "rmtree", "removedirs"}
TEMP_CTOR_NAMES = {"TemporaryDirectory", "TemporaryFile"}
EXCLUDE_DIRS = {"tests", "fixtures", "docs", "examples"}
TEST_DIRS = {"tests", "fixtures"}


def normalize(text):
    text = text.lower().replace("n't", " not")
    text = text.replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def strip_fenced(text):
    lines = text.splitlines()
    out = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def split_sentences(text):
    parts = re.split(r"[.!?\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _phrase_in(sentence, phrase):
    return re.search(r"\b" + re.escape(phrase) + r"\b", sentence) is not None


def _strip_phrase(sentence, phrase):
    return re.sub(r"\b" + re.escape(phrase) + r"\b", " ", sentence)


def extract_claims(root, ignore):
    """Return {family: [phrase, ...]} found in root README + docs/**/*.md."""
    doc_files = []
    readme = root / "README.md"
    if readme.is_file() and not readme.is_symlink():
        doc_files.append(readme)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for path in sorted(docs_dir.rglob("*.md")):
            if not path.is_symlink():
                doc_files.append(path)
    found = {}
    for path in doc_files:
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
            continue
        text = strip_fenced(path.read_text(encoding="utf-8", errors="replace"))
        for sentence in split_sentences(normalize(text)):
            for phrase, family in PHRASE_FAMILIES:
                if not _phrase_in(sentence, phrase):
                    continue
                if family == CLEANUP:
                    # Remove this phrase's span first, then check the
                    # remainder for a negation token. This lets
                    # self-negating phrases ("leaves no temporary
                    # files") count while "never cleans up temporary
                    # files" is suppressed (leftover "never") in favour
                    # of its NOCLEANUP match.
                    remainder = _strip_phrase(sentence, phrase)
                    if set(remainder.split(" ")) & NEGATIONS:
                        continue
                found.setdefault(family, [])
                if phrase not in found[family]:
                    found[family].append(phrase)
    return found


def _named_temporary_file_is_evidence(node):
    """delete absent or True literal -> self-deleting; anything else no."""
    for kw in node.keywords:
        if kw.arg == "delete":
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return True


def collect_evidence(path, rel):
    """Return cleanup-evidence items found in one .py file (AST only)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    local_defs = set()
    from_imports = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_defs.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module in ("tempfile", "atexit"):
                for alias in node.names:
                    from_imports[alias.asname or alias.name] = (
                        node.module, alias.name)
    evidence = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            attr = func.attr
            if attr in CLEANUP_CALL_ATTRS:
                evidence.append("%s:%d: %s()" % (rel, node.lineno, attr))
            elif attr in TEMP_CTOR_NAMES:
                evidence.append("%s:%d: %s()" % (rel, node.lineno, attr))
            elif attr == "NamedTemporaryFile":
                if _named_temporary_file_is_evidence(node):
                    evidence.append("%s:%d: NamedTemporaryFile()" % (rel, node.lineno))
            elif attr == "register" and isinstance(func.value, ast.Name):
                if func.value.id == "atexit":
                    evidence.append("%s:%d: atexit.register()" % (rel, node.lineno))
        elif isinstance(func, ast.Name):
            name = func.id
            if name in local_defs:
                continue
            origin = from_imports.get(name)
            if origin is None:
                continue
            module, orig = origin
            if orig in TEMP_CTOR_NAMES and module == "tempfile":
                evidence.append("%s:%d: %s()" % (rel, node.lineno, name))
            elif orig == "NamedTemporaryFile" and module == "tempfile":
                if _named_temporary_file_is_evidence(node):
                    evidence.append("%s:%d: NamedTemporaryFile()" % (rel, node.lineno))
            elif orig == "register" and module == "atexit":
                evidence.append("%s:%d: atexit.register()" % (rel, node.lineno))
    return evidence


def _iter_py_files(root):
    for path in sorted(root.rglob("*.py")):
        if path.is_symlink():
            continue
        yield path


def audit(root, ignore=()):
    claims = extract_claims(root, ignore)
    prod_files = []
    prod_evidence = []
    test_evidence = []
    for path in _iter_py_files(root):
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
            continue
        parts = set(path.relative_to(root).parts[:-1])
        name = path.name
        if parts & TEST_DIRS:
            test_evidence.extend(collect_evidence(path, rel))
        elif parts & EXCLUDE_DIRS:
            continue
        elif name.startswith("test_") or name.endswith("_test.py"):
            test_evidence.extend(collect_evidence(path, rel))
        else:
            prod_files.append(path)
            prod_evidence.extend(collect_evidence(path, rel))
    findings = []
    verified = []

    def handle(family, false_rule, testonly_rule):
        if family not in claims:
            return
        if prod_evidence:
            verified.append({"family": family, "phrases": claims[family]})
        elif test_evidence:
            findings.append({"rule": testonly_rule, "severity": "MEDIUM",
                             "family": family, "evidence": sorted(test_evidence)})
        elif not prod_files:
            findings.append({"rule": false_rule, "severity": "HIGH",
                             "family": family, "evidence": ["no-source"]})
        else:
            findings.append({"rule": false_rule, "severity": "HIGH",
                             "family": family, "evidence": []})

    # Reverse rule: a no-cleanup claim is falsified by production
    # cleanup evidence, so handle it with the roles swapped.
    if CLEANUP in claims:
        handle(CLEANUP, "documented-cleanup-claim-false",
               "documented-cleanup-claim-false-test-only")
    if NOCLEANUP in claims:
        if prod_evidence:
            findings.append({"rule": "documented-no-cleanup-claim-false",
                             "severity": "HIGH", "family": NOCLEANUP,
                             "evidence": sorted(prod_evidence)})
        elif test_evidence:
            findings.append({"rule": "documented-no-cleanup-claim-false-test-only",
                             "severity": "MEDIUM", "family": NOCLEANUP,
                             "evidence": sorted(test_evidence)})
        elif not prod_files:
            findings.append({"rule": "documented-no-cleanup-claim-false",
                             "severity": "HIGH", "family": NOCLEANUP,
                             "evidence": ["no-source"]})
        else:
            verified.append({"family": NOCLEANUP, "phrases": claims[NOCLEANUP]})
    return {
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "verified_claims": verified,
        "claims": claims,
    }


def result_json(result):
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


def format_human(result):
    lines = ["status: %s" % result["status"]]
    for finding in result["findings"]:
        lines.append("%s %s (%s)" % (finding["severity"], finding["rule"],
                                     finding["family"]))
        for item in finding["evidence"]:
            lines.append("  evidence: %s" % item)
    for claim in result["verified_claims"]:
        lines.append("verified: %s (%s)" % (claim["family"],
                                            ", ".join(claim["phrases"])))
    return "\n".join(lines) + "\n"
