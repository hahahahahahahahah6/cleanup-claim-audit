# cleanup-claim-audit

Offline auditor for documented temporary-file cleanup promises in Python
projects. It checks whether a project's docs promise temp-file tidiness
(or promise the opposite) and whether its Python source backs that
promise up. It executes nothing, uses no network, and
never reads `.env` file contents.

## Usage

```sh
cleanup-claim-audit <project-root>
cleanup-claim-audit <project-root> --json
cleanup-claim-audit <project-root> --fail-on HIGH
cleanup-claim-audit <project-root> --ignore 'docs/draft-*'
```

Exit codes: `0` PASS, `2` FAIL, `1` usage error. `--fail-on HIGH` makes
MEDIUM-only results exit `0`. `--json` prints
`{status, findings, verified_claims, claims}`.

## Claims checked

Claims come from prose in the root `README.md` plus `docs/**/*.md`.
Fenced code blocks are excluded; inline code counts as prose. Claim
phrases are exact phrases (see below, shown in a fenced block so this
very README does not itself make a claim the tool would audit):

```
cleanup family: cleans up temporary files, cleans up temp files,
removes temporary files, temporary files are cleaned up,
no temporary files left behind, leaves no temporary files,
cleans up after itself, automatically cleans up temporary files
nocleanup family: does not clean up temporary files,
never cleans up temporary files, leaves temporary files behind,
no cleanup of temporary files, does not clean up after itself
```

A sentence in the cleanup family is suppressed when, after removing
the matched phrase, a negation token (`no`, `not`, `never`, `without`)
remains — so a sentence that only denies cleanup is claimed by the
nocleanup family, not by both. Bare nouns such as "temporary files" or
"cleanup" alone are not claims.

## Evidence

Cleanup evidence in production Python source (AST only):

- attribute calls named `unlink`, `remove`, `rmtree`, or `removedirs`
  (any receiver: `os.unlink`, `Path.unlink`, `shutil.rmtree`, ...)
- `TemporaryDirectory` / `TemporaryFile` calls (self-cleaning)
- `atexit.register` calls (teardown registration)
- `NamedTemporaryFile` with the `delete` argument absent or `True`
  (self-deleting; the default is `delete=True`)

Not evidence: bare imports alone, `mkstemp` / `mkdtemp` calls
(creation, not cleanup), `NamedTemporaryFile(delete=False)`, `open()`
writes, or anything in comments and strings.

## Rules

- `documented-cleanup-claim-false` (HIGH): a cleanup claim with zero
  production cleanup evidence; `documented-cleanup-claim-false-test-only`
  (MEDIUM) when the evidence exists only under `tests/` or `fixtures/`.
- `documented-no-cleanup-claim-false` (HIGH): a no-cleanup claim with
  production cleanup evidence; `...-test-only` (MEDIUM) for test-only
  evidence.
- No production source at all yields a HIGH finding with evidence
  `["no-source"]` for either claimed family. No claim yields PASS.

## Differentiation

- shutdown-claim-audit asks whether a process defends its teardown
  when interrupted (signal handlers); this asks whether stray temp
  files get deleted during a normal run, signal or no signal.
- atomic-claim-audit asks whether a single write lands atomically via
  temp file plus replace; this asks whether stray temp files get
  deleted, not how a write lands.
- readonly-claim-audit asks whether files are written at all; this
  asks whether stray temp files get deleted after being written.
- streaming-claim-audit asks about memory behaviour; this asks about
  temp files on disk.
- bandit and ruff find code issues; they never check docs promises.
- The `tempfile` docs describe cleanup mechanisms at runtime; they
  never check docs against code.

## Honest limitations

- Exact phrases, not semantics: reworded promises are missed.
- Dead code counts as evidence, and a cleanup call anywhere in a file
  counts even outside a `finally` block or an `atexit` handler.
- Receiver types are not inferred: any `.unlink()` / `.remove()` /
  `.rmtree()` call counts, whatever the receiver is.
- Attribute calls always count; bare-name calls count only when
  imported from `tempfile` / `atexit` (aliases followed).
- Dynamic temp paths are not tracked, and `NamedTemporaryFile` with a
  non-literal `delete` value is not counted as cleanup.
- A cleanup call is not proof the right files are removed, only that
  a cleanup mechanism exists in the source.


## Development

```sh
python3 -m unittest discover -s tests -v
```

## License

MIT
