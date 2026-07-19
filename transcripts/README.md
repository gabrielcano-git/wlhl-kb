# Transcript source folder

The Streamlit application reads transcript text from Turso and requires network access. It does not read files from this folder at runtime.

This folder exists only for the separate, local database-maintenance utilities. Those utilities may ingest newly published canonical `.txt` transcripts into a local SQLite working file before an intentional administrative migration. They never update the production Turso database automatically. Existing source files should not be moved, renamed, or overwritten.
