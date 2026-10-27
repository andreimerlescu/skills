# Incident response: a secret has been exposed

Load the moment you discover (or cause) any of: a secret in a commit, pushed branch, PR, issue, image layer, binary, package, log, build artifact, chat transcript, screenshot or public document. Rule `S10` applies: say so plainly. Do not minimize, do not quietly fix and move on.

## 1. Immediate actions (in this order)

1. **Stop.** Add no features. Do not push, tag, release, publish a package, or build a new image until containment is done.
2. **Tell the user now**, in plain words: what kind of secret, where it is exposed, how far it may have travelled (local only / committed locally / pushed / published / embedded in a distributed binary), and that **it must be rotated**. Do not print the secret.
3. **Rotation is the fix; deletion is not.** Anything that has been committed, pushed, embedded in a distributed binary, or pasted into a service must be treated as compromised, forever. Ask the user to revoke/rotate it with the provider. Offer to prepare the code change that makes rotation painless (runtime injection), but do not claim the incident is resolved by code changes.
4. **Contain the source.** Add ignore rules; remove the file from the index (`git rm --cached <file>`); remove embed/COPY/default usages; replace with runtime injection (SKILL.md §3).
5. **Find every copy.** `git log --all -p -G<fragment>` (take the fragment from the file inside the shell, not typed by you); `git grep`; scan built artifacts, image layers, CI logs, caches, package tarballs, `dist/`, `build/`, coverage reports, docs, and fixtures. Use `scripts/secret-scan.sh --literal-file <file> --artifact <each artifact>`.
6. **Assess blast radius.** What can the credential do? (scope, resources, spend, data). Are there audit logs to check for misuse? Recommend the user review the provider's access logs for the exposure window.

## 2. History rewriting (only with the user's go-ahead)

Rewriting history is destructive and changes commit IDs for everyone. Do it only if the user asks, after rotation, and after warning that forks/clones/caches may retain the old data.

- Not yet pushed: amend or interactively reset the local commits, or `git reset --soft` and recommit without the file. Then `git reflog expire --expire=now --all && git gc --prune=now` if asked to purge local objects.
- Already pushed: use `git filter-repo --invert-paths --path <file>` (or `--replace-text` for in-line strings), force-push with lease to protected branches only with explicit approval, ask collaborators to re-clone, and contact the host (GitHub support / secret scanning) to purge cached views of the commits and pull-request refs.
- Never run `git push --force` to shared branches on your own initiative. Never rewrite history that others rely on without telling the user the consequences.

## 3. Embedded in a built binary or image

Treat the artifact as compromised. Delete it from registries, release pages, package indexes and CDNs; rebuild after the fix; invalidate old tags and digests; confirm the new artifact is clean with the literal search; rotate the credential. Say so in the report even if the artifact was only built locally and never left the machine, and let the user judge.

## 4. After containment

- Add a regression test or CI check that fails if the pattern returns (scanner in CI, pre-commit hook, a unit test asserting the flag has no default and `-h` has no value).
- Write the incident into the report: `Exposure: SECRET WAS EXPOSED via <path/channel>: ROTATE`, plus what you changed.
- If an automated secret scanner or push protection flagged the secret, never use the "allow secret"/bypass link on a real credential.

## 5. If the secret was only in the conversation or tool output

Say that it appeared in the session transcript. Do not repeat it. Recommend rotation if it is a real production credential and the transcript may be stored or shared. Continue the task using file/env injection so no further copies are made.
