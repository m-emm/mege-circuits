# PyPI Publishing

`mege-circuits` publishes from GitHub Actions to PyPI with Trusted Publishing.
There is no long-lived `PYPI_API_TOKEN` secret in GitHub. PyPI trusts one
specific repository, workflow file, and environment, then mints a short-lived
token for that workflow run.

## One-Time Auth Setup

The GitHub side uses an environment named `pypi`. It should allow deployments
from tags matching `v*`:

```bash
gh api repos/:owner/:repo/environments/pypi \
  --jq '{name, deployment_branch_policy}'

gh api repos/:owner/:repo/environments/pypi/deployment-branch-policies \
  --jq '.branch_policies[] | {name, type}'
```

Expected values:

```text
name: pypi
deployment_branch_policy.protected_branches: false
deployment_branch_policy.custom_branch_policies: true
deployment policy: {"name": "v*", "type": "tag"}
```

The PyPI side must be configured in PyPI itself. For the first publication of a
new project, create a pending publisher:

- Project name: `mege-circuits`
- Owner: `m-emm`
- Repository name: `mege-circuits`
- Workflow filename: `publish-to-pypi.yml`
- Environment name: `pypi`

For an existing PyPI project, add the same values under that project's
Publishing settings. The workflow name and environment name must match exactly.

Useful references:

- PyPI pending publishers:
  <https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>
- PyPI trusted publishing:
  <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
- Python Packaging GitHub Actions publishing guide:
  <https://packaging.python.org/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/>
- GitHub OIDC for PyPI:
  <https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-pypi>

## Release Flow

Run checks locally:

```bash
python -m pytest
python -m pytest --runslow -m slow
rm -rf dist build
python -m build
python -m twine check dist/*
./precommit.sh
```

Create and push a release tag:

```bash
git tag -a v0.1.1 -m "mege-circuits 0.1.1"
git push origin v0.1.1
```

The `Publish Python Package to PyPI` workflow will:

1. Run the fast test suite on Python 3.11 and 3.12.
2. Run slow stripboard routing regressions on Python 3.12.
3. Build source and wheel distributions.
4. Check distribution metadata with Twine.
5. Publish to PyPI only when the workflow was triggered by a `v*` tag.

Manual `workflow_dispatch` runs build and check the distributions, but they do
not publish because publishing is gated on `refs/tags/v*`.

Versions come from `setuptools-scm`. A tag like `v0.1.1` publishes version
`0.1.1`. PyPI versions are immutable, so a failed release that reached PyPI
must be fixed with a new version tag.

## Troubleshooting

`invalid-publisher` or `unauthorized` means the PyPI trusted publisher tuple did
not match the workflow run. Re-check owner, repository, workflow filename, and
environment name.

If the workflow builds artifacts but waits or fails before publish, check the
GitHub `pypi` environment deployment rules and approve the deployment if an
approval rule is added later.

If PyPI rejects an upload because the version already exists, create a new tag
with a new version. Existing PyPI files cannot be replaced.
