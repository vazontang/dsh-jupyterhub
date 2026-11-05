---
name: jupyter-first
description: Run business Python or Bash in the user's Jupyter notebook through the mcp__jupyter__* tools so the user sees and can re-run the code. Use for data work, scripts, analysis, ops commands and anything the user may want to inspect or tweak; not for editing repo source files.
---

# Jupyter first

You run inside the user's JupyterLab server. The user watches the notebook in
JupyterLab while you work, so code you run there is visible, re-runnable and
editable by them. Prefer it over your own shell tool for **business code**.

## When to use the notebook

- Data loading, analysis, plots, quick experiments, API calls, ops checks.
- Any Python the user may want to read, re-run or change.
- Bash the user should see: put it in a code cell with `%%bash` as the first line.

Use your own file and shell tools instead for: editing source files in a repo,
git operations, running a project's test suite, installing packages.

## How

1. `mcp__jupyter__list_notebooks`; if none fits, `mcp__jupyter__use_notebook`
   with `mode: "create"` and a descriptive `notebook_path`
   (for example `work/2026-11-05-sales-check.ipynb`). Reuse the user's open
   notebook when they point at one.
2. Add a short markdown cell that says what the next cells do
   (`mcp__jupyter__insert_cell`, `cell_type: "markdown"`).
3. Run code with `mcp__jupyter__insert_execute_code_cell`, one logical step per
   cell, appended at the end (`cell_index: -1`) unless the user asked otherwise.
4. Read errors from the cell output, fix the cell with
   `mcp__jupyter__overwrite_cell_source` and re-run it with
   `mcp__jupyter__execute_cell`, instead of adding a new broken copy.
5. Long jobs: pass a `timeout`; if it is long-running, tell the user which cell
   is running rather than waiting silently.
6. In your reply, name the notebook and the cell numbers you used.

## Rules

- Never print secrets. Credentials are in `/run/user-secrets` (tmpfs) and in
  environment variables; refer to them by path or variable name only.
- Do not `pip install` into the base environment without asking; use
  `%pip install --user <pkg>` in a cell when the user agrees.
- Keep outputs small: summarise DataFrames with `.head()` / `.describe()`.
