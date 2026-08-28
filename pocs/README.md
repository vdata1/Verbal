# Minimal proofs of concept

One self-contained file per defect. No dependencies, no build step: each file runs
on any JS engine and prints one line per case.

```console
$ node     f003_bun_ignorecase_property_escape.js
$ bun      f003_bun_ignorecase_property_escape.js
$ deno run --quiet f003_bun_ignorecase_property_escape.js
```

Every file names the engine that is wrong, states the spec-required answer inline
as `(want ...)`, and includes the **controls that isolate the trigger** — nearby
cases where all three engines agree. A control that also failed would mean the
engine was broadly broken rather than wrong on this specific construct.

| file | what differs | wrong engine | mechanism |
|---|---|---|---|
| [`f001_deno_unicode17_property_tables.js`](f001_deno_unicode17_property_tables.js) | `\p{...}` under `/u` misses Unicode 17.0 code points | **deno** | property-table data lag |
| [`f002_bun_anchor_hoist_zero_matchable_group.js`](f002_bun_anchor_hoist_zero_matchable_group.js) | `^` in a zero-matchable group anchors the whole pattern | **bun** | Yarr JIT miscompile |
| [`f003_bun_ignorecase_property_escape.js`](f003_bun_ignorecase_property_escape.js) | `\p{...}` is not case-folded under `/i` | **bun** | missing canonicalization step |
| [`f004_bun_backtracking_step_cap.js`](f004_bun_backtracking_step_cap.js) | backtracking is abandoned at a step budget, returning a silent `false`/`null` | **bun** | resource cap without a signal |
| [`f005_bun_sticky_dotstar_backtrack.js`](f005_bun_sticky_dotstar_backtrack.js) | sticky `y` with a leading `.*` that must backtrack returns `null` | **bun** | shared/interpreter path |
| [`bugA_bun_vmode_class_lone_surrogate.js`](bugA_bun_vmode_class_lone_surrogate.js) | a `v`-mode character class returns a lone surrogate | **bun** | Yarr JIT miscompile |
| [`bugB_jsc_lastindex_mid_surrogate.js`](bugB_jsc_lastindex_mid_surrogate.js) | `lastIndex` pointing inside a surrogate pair | **bun** | code-unit vs code-point mapping |
| [`bugF_webkit_yarr_dotall_offset.js`](bugF_webkit_yarr_dotall_offset.js) | the `s` flag shifts where a match starts when `lastIndex` > 0 | **bun** (upstream JSC) | Yarr JIT miscompile |
| [`v8_interpreter_cap_tier_disagreement.js`](v8_interpreter_cap_tier_disagreement.js) | the regexp interpreter abandons backtracking at a budget and disagrees with V8's own compiler on consecutive calls | **node and deno** | resource cap without a signal |
| [`n01_bun_vmode_raw_nul_rejected.js`](n01_bun_vmode_raw_nul_rejected.js) | a raw NUL in a `v`-mode class is rejected | **bun** | parser |
| [`n02_bun_nonascii_identity_escape.js`](n02_bun_nonascii_identity_escape.js) | a non-ASCII `IdentityEscape` is accepted under `/u` | **bun** | parser |
| [`n03_bun_vmode_trailing_dash_accepted.js`](n03_bun_vmode_trailing_dash_accepted.js) | an unescaped trailing `-` in a `v`-mode class is accepted | **bun 1.3.11** | parser |

One extra file is not a separate defect:

- [`threeway_split_f001_f003.js`](threeway_split_f001_f003.js) — F001 and F003
  composed, so a single call returns **three different answers** on the three
  engines. On other inputs the same pair splits 2-vs-1 with the *majority* wrong,
  which is why a "two of three engines agree" oracle is not sound here.

## Reading the results

**Some of these are JIT miscompiles.** Where the table says so, the same binary
disagrees with itself between its JIT and its interpreter, which settles the
correct answer without any cross-engine vote and without a spec argument:

```console
$ BUN_JSC_useRegExpJIT=0 bun f002_bun_anchor_hoist_zero_matchable_group.js   # now correct
```

**`bugF` is not bun-specific.** Apple's shipped system `jsc` reproduces it
case-for-case with no bun involved, so the defect is in upstream Yarr and is live
in Safari. The file's header carries the one-line `jsc` invocation.

**`bugB` sits in an area the spec leaves open.** It is an interop divergence, not
a clean conformance violation: a literal reading of `RegExpBuiltinExec` yields a
third answer that neither V8 nor JSC returns. The case rests on the consequences
the file demonstrates — `test()` goes `false`, `matchAll` drops a match, sticky
returns `null`.

**Two files need no second engine at all.** `f004` and
`v8_interpreter_cap_tier_disagreement` both use *nullable* patterns, which match
`""` at index 0 of every subject, so returning `null` is wrong on the accused
engine's own terms. Each demonstrates the empty match in the same process.

**`f004` and the V8 file are slow by nature** — a few seconds and a couple of
minutes respectively. They need genuine exponential backtracking, which the V8
engines perform honestly. In the V8 file the *interpreter* takes ~143 s to return
the wrong answer while the *compiler* takes ~28 s to return the right one.

**`n03` needs bun 1.3.11**, being fixed by 1.3.14, so on the pinned engines every
line reads "ok". The file detects this and says which side of the fix the running
build is on, rather than looking like a broken reproducer:

```console
$ curl -fsSL -o bun.zip https://github.com/oven-sh/bun/releases/download/bun-v1.3.11/bun-darwin-aarch64.zip
$ unzip -q bun.zip && ./bun-darwin-aarch64/bun n03_bun_vmode_trailing_dash_accepted.js
  bun 1.3.11: REPRODUCES -- /[a-]/v compiled and must not have.
```

## Verified on

node v26.5.0 (V8 14.6.202), bun 1.3.14 (JavaScriptCore), deno 2.9.1 (V8
14.9.207) — the versions the Docker image pins and verifies at container start.
Every file above was re-run on these three engines and reproduces as documented,
except `n03`, which is fixed in 1.3.14 and was verified against bun 1.3.11.
