# Technical Design Document: `re-ass`

NOTE: `re-ass` is short for “Research Assistant”.

## 1. System Overview
**`re-ass`** is a lightweight, locally hosted Python script running on a Mac. It executes once daily to fetch new ArXiv papers matching ranked user preferences, limits the batch to the top 3, and delegates the heavy lifting of summarization and formatting to an existing `summarise-paper` LLM skill via the `claude` CLI. It then integrates the results into an Obsidian vault's Daily Note and a static weekly overview note, which is archived and reset every Sunday.

## 2. Vault File & Directory Structure
The script expects and interacts with the following Obsidian vault structure (user configurable with defaults):

```text
/Obsidian_Vault
├── re-ass-preferences.md           <-- Ordered list of user interests
├── this-weeks-arxiv-papers.md      <-- The active, rolling weekly overview
├── /Papers                         <-- Handled entirely by the summarise-paper skill
├── /Daily                          <-- Standard Obsidian Daily Notes (e.g., 2026-03-21.md)
├── /Weekly_Archive                 <-- Archived weekly notes (e.g., 2026-03-22-arxiv.md)
└── /Templates
    └── weekly-arxiv-template.md    <-- Template for resetting the weekly note
```

## 3. Core Components

### 3.1. Preference Parser (`config_manager.py`)
*   **Input:** Reads `re-ass-preferences.md`.
*   **Format:** A simple Markdown numbered list (e.g., `1. Agents`, `2. RAG`, `3. Yann LeCun`). 
*   **Function:** Extracts the list into an ordered Python array where index represents priority.

### 3.2. ArXiv Fetcher & Ranker (`arxiv_fetcher.py`)
*   **Querying:** Uses the `arxiv` Python package to fetch papers from the last 24 hours based on top preferences.
*   **Ranking & Truncation:** 
    *   Scores each paper based on the highest-ranked preference it matches. 
    *   Strictly truncates the list to a maximum of 3 papers (`top_papers[:3]`).

### 3.3. Summarizer Delegation (`llm_orchestrator.py`)
*   **Execution:** Shells out to the local CLI LLM using Python's `subprocess` module. 
*   **Action:** For each of the top 3 papers, it executes a simple bash command that invokes an existing skill:
    ```bash
    claude -p "Use summarise-paper skill to summarise <arxiv_url> and write to <papers_directory_path>"
    ```
*   **Wait State:** Uses `subprocess.run(..., wait=True)` to block execution until the skill finishes creating the individual paper note in the Obsidian `/Papers` directory.
*   **Micro-Summary:** Makes a secondary, fast CLI call to generate a 1-2 line summary of the abstract specifically for injection into the daily/weekly notes.

NOTE: keep configurable - eg Claude Code (default), Codex CLI, Gemini CLI, Copilot CLI etc

### 3.4. Obsidian Integration (`vault_manager.py`)
*   **Daily Note Updater:** 
    *   Locates today's daily note (e.g., `2026-03-21.md`).
    *   Appends a section: `## Today's Top Paper`.
    *   Injects a Wikilink to the #1 ranked paper and its 1-2 line summary.
*   **Weekly Note Manager:**
    *   **Rolling File:** Always writes to `this-weeks-arxiv-papers.md` in the vault root (or designated folder).
    *   **Appending:** Adds the new papers under a `### [Day of Week]` header using Wikilinks (`[[Paper_Title]]`) and their 1-2 line summaries.
    *   **Rolling Synthesis:** Extracts the existing synthesis paragraph. Passes the old synthesis + the 3 new 1-2 line summaries to the LLM via CLI: *"Update this weekly synthesis incorporating these new papers. Max 100 words."* Overwrites the top synthesis block.
    *   **Sunday Reset Rotation:** 
        *   If `datetime.today().weekday() == 6` (Sunday):
        *   *Move/Rename:* `this-weeks-arxiv-papers.md` -> `/Weekly_Archive/YYYY-MM-DD-arxiv.md` (e.g., `2026-03-22-arxiv.md`).
        *   *Reset:* Copy `/Templates/weekly-arxiv-template.md` to create a fresh `this-weeks-arxiv-papers.md`.

---

## 4. Daily Execution Flow

1.  **Parse:** Read `re-ass-preferences.md` to get user priorities.
2.  **Fetch & Rank:** Query ArXiv. Score and keep only the Top 3 papers.
3.  **Process via Skill (Loop):**
    *   For Paper in Top 3:
        *   Execute: `claude -p "Use summarise-paper skill to summarise {arxiv_url} and write to {vault_path}/Papers"`
        *   Extract a 1-2 line micro-summary for the overview notes.
4.  **Update Daily Note:**
    *   Write `[[Top_Paper_Title]] - <1-2 line summary>` into today's Daily Note under `## Today's Top Paper`.
5.  **Update Active Weekly Note:**
    *   Check if today is Sunday. If yes:
        *   Rename `this-weeks-arxiv-papers.md` to `YYYY-MM-DD-arxiv.md` and move to archive.
        *   Duplicate `weekly-arxiv-template.md` to create a new `this-weeks-arxiv-papers.md`.
    *   Read current synthesis from `this-weeks-arxiv-papers.md`.
    *   Call LLM CLI to generate a *New Synthesis (<100 words)* based on the 3 new papers.
    *   Rewrite the top of `this-weeks-arxiv-papers.md` with the new synthesis.
    *   Append today's 3 papers (Wikilinks + micro-summaries) to the bottom of the note.
6.  **Exit Script.**

---

## 5. Templates

**Weekly Overview Template (`weekly-arxiv-template.md`)**
```markdown
# This Week's ArXiv Overview

## Synthesis
*(A synthesis of this week's papers will be automatically generated here. Max 100 words.)*

---
## Daily Additions
```

**User Preferences File (`re-ass-preferences.md`)** - should also identify which arxiv categories to pull from
```markdown
# Arxiv Priorities
1. Large Language Model Reasoning
2. Agents and Tool Use
3. Anthropic (Author/Institution)
4. MMLU (Dataset)
```

---

## 6. Automation

**macOS launchd configuration (`com.user.re-ass.plist`)**
Executes the script quietly in the background every morning.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <key>com.user.re-ass</key>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/YourName/Path/To/re-ass/main.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/re-ass.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/re-ass.err</string>
</dict>
</plist>
```

## 7. Build Instructions (for Claude Code)
When handing this to your Claude Code agent to build, you can structure your prompts as follows:
1. *"Read this TDD. Write `arxiv_fetcher.py` using the `arxiv` library to fetch and rank the top 3 papers based on a dummy list of string preferences."*
2. *"Write `llm_orchestrator.py` using Python's `subprocess`. It should take an arxiv URL and a target directory, and run the bash command `claude -p "Use summarise-paper skill..."` exactly as specified in the TDD."*
3. *"Write `vault_manager.py`. Focus first on the Sunday rotation logic: renaming `this-weeks-arxiv-papers.md` to the archive and copying the template."*