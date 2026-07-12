# Lead Pipeline Prototype

This is the first slice of the workflow: collect Google Places-style lead data, qualify it, generate demo site/email files, and save everything into files Python can reload later.

## Current Flow

```text
raw Places results
  -> lead filter
  -> qualified_leads.json
  -> one folder per lead
  -> generated static site + outreach email
  -> local QA report
```

The prototype can run without API access by using `data/raw_places.sample.json`.

## Quick Start

```powershell
python .\lead_pipeline.py qualify --input .\data\raw_places.sample.json
python .\lead_pipeline.py generate
python .\lead_pipeline.py qa
python .\lead_pipeline.py status
```

With the bundled Codex Python runtime in this workspace:

```powershell
& 'C:\Users\morri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\lead_pipeline.py qualify --input .\data\raw_places.sample.json
& 'C:\Users\morri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\lead_pipeline.py generate
& 'C:\Users\morri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\lead_pipeline.py qa
& 'C:\Users\morri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\lead_pipeline.py status
```

To fetch real Google Places Text Search results:

```powershell
$env:GOOGLE_PLACES_API_KEY = 'your-api-key'
python .\lead_pipeline.py fetch-text --query "dentists in Dayton OH" --included-type dentist --output .\data\raw_places.json
python .\lead_pipeline.py qualify --input .\data\raw_places.json
```

Generated files go to:

```text
leads/
  qualified_leads.json
  <lead-slug>/
    lead.json
    brief.txt
    status.json
    generation_prompt.txt
    page_structure.json
    copy.txt
    email.txt
    qa_report.json
    qa_report.txt
    site/
      index.html
      styles.css
      script.js
```

## Commands

### `fetch-text`

Fetches one page of real Google Places Text Search results and normalizes it into the same shape as the sample data.

```powershell
python .\lead_pipeline.py fetch-text --query "dentists in Dayton OH" --included-type dentist --output .\data\raw_places.json
```

Requires `GOOGLE_PLACES_API_KEY`.

### `qualify`

Filters raw Places results into lead folders.

```powershell
python .\lead_pipeline.py qualify --input .\data\raw_places.sample.json
```

### `generate`

Reads `lead.json` and `brief.txt`, then writes demo assets for each lead.

```powershell
python .\lead_pipeline.py generate --leads-dir .\leads
```

Use `--lead-id <folder-name>` for one lead, and `--force` to overwrite an existing generated site.

### `qa`

Runs basic checks against generated files.

```powershell
python .\lead_pipeline.py qa --leads-dir .\leads
```

The QA step currently checks that expected files exist, the business name appears in the site, the viewport meta tag is present, and the email still has the `{{LIVE_DEMO_URL}}` placeholder.

### `status`

Prints each lead's current workflow state.

```powershell
python .\lead_pipeline.py status --leads-dir .\leads
```

## Filter Rules

Defaults are in `config.example.json`:

- business has no website
- rating is at least `4.2`
- review count is at least `10`
- category matches one of the target industries

## Later

When you are ready to connect the real Google Places API, wire the fetch step to write raw results into `data/raw_places.json`, then run the same qualification command against that file.

The `fetch-text` command uses the current Places API Text Search endpoint:

```text
https://places.googleapis.com/v1/places:searchText
```

It requests only the fields needed for this prototype: name, address, phone, rating, review count, types, website URI, and business status.

## API Generation Hook

The current `generate` command uses a deterministic local generator so the pipeline works without a model key. It also writes `generation_prompt.txt` per lead. That file is the handoff point for Claude/OpenAI/etc.:

1. read `generation_prompt.txt`
2. send it to the model
3. write the returned copy/site/email into the same lead folder
4. run `qa`

That keeps the pipeline debuggable: every lead folder contains the input, generated output, and QA result.
