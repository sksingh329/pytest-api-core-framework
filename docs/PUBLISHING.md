# Publishing to PyPI

This document explains how to publish `pytest-api-core` to public PyPI using the GitHub Actions workflow.

## Prerequisites

### 1. PyPI Account Setup

1. Create an account at [https://pypi.org](https://pypi.org)
2. Enable Two-Factor Authentication (required for publishing)
3. Register the project name `pytest-api-core` (or your chosen name)

### 2. Configure Trusted Publishing (Recommended)

GitHub Actions supports **Trusted Publishing** (no API tokens needed):

1. Go to [https://pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/)
2. Click **Add a new pending publisher**
3. Fill in the form:
   - **PyPI Project Name:** `pytest-api-core`
   - **Owner:** `<your-github-username-or-org>`
   - **Repository:** `pytest-api-core-framework` (or your repo name)
   - **Workflow name:** `publish-public.yml`
   - **Environment name:** `pypi`
4. Click **Add**

### 3. Alternative: API Token Method

If not using Trusted Publishing:

1. Go to [https://pypi.org/manage/account/token/](https://pypi.org/manage/account/token/)
2. Create a new API token scoped to the `pytest-api-core` project
3. Copy the token (starts with `pypi-...`)
4. Add it to GitHub Secrets:
   - Go to your repo → **Settings** → **Secrets and variables** → **Actions**
   - Click **New repository secret**
   - Name: `PYPI_API_TOKEN`
   - Value: `<your-token>`

Then modify the workflow to use the token instead of Trusted Publishing:

```yaml
# Replace the "Publish to PyPI (Trusted Publishing)" step with:
- name: Publish to PyPI (API Token)
  run: |
    twine upload \
      --username __token__ \
      --password "${{ secrets.PYPI_API_TOKEN }}" \
      --non-interactive \
      --verbose \
      dist/*
```

---

## Publishing a New Version

### Step 1: Prepare the release

1. Update `CHANGELOG.md` with release notes
2. Commit all changes
3. Push to `main` branch

### Step 2: Trigger the workflow

1. Go to **Actions** tab in GitHub
2. Select **Publish to Public PyPI** workflow
3. Click **Run workflow** button
4. Fill in the inputs:
   - **Version:** `1.0.1` (without 'v' prefix)
   - **Run tests:** ✅ (recommended)
5. Click **Run workflow**

### Step 3: Monitor the workflow

The workflow will:
1. ✅ Run tests on Python 3.9, 3.10, 3.11, 3.12 (if enabled)
2. 📝 Update version in `pyproject.toml`
3. 🔨 Build source distribution (.tar.gz) and wheel (.whl)
4. 🔍 Verify the distributions
5. 🚀 Upload to PyPI
6. 📦 Create GitHub release with artifacts
7. 🏷️ Create git tag `v1.0.1`

### Step 4: Verify publication

1. Check PyPI: https://pypi.org/project/pytest-api-core/
2. Test installation:
   ```bash
   pip install pytest-api-core==1.0.1
   ```

---

## Workflow Options

### `version` (required)
- Format: `X.Y.Z` (e.g., `1.0.1`, `2.3.0-beta1`)
- Do NOT include 'v' prefix
- Follows semantic versioning: `MAJOR.MINOR.PATCH`

### `run_tests` (optional, default: true)
- **true** — Runs full test suite on Python 3.9-3.12 before publishing
- **false** — Skips tests (use for hotfixes or when tests already passed)

---

## Troubleshooting

### "Project name already registered"
- The package name is taken on PyPI
- Change `name = "pytest-api-core"` in `pyproject.toml` to something unique

### "Trusted publisher not configured"
- Complete the PyPI Trusted Publishing setup (see Prerequisites)
- Or switch to API token method

### "Tests failed"
- Review test logs in the Actions tab
- Fix issues and re-run the workflow

### "Version already exists"
- PyPI doesn't allow re-uploading the same version
- Bump the version number and try again
- Or use `post1` suffix: `1.0.1.post1`

---

## Manual Publishing (without GitHub Actions)

If you prefer local publishing:

```bash
# Update version in pyproject.toml
vim pyproject.toml

# Build
python -m build

# Upload to PyPI
twine upload dist/*
```

Enter your PyPI username (`__token__`) and API token when prompted.
