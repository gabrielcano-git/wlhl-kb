# Transcript source folder

The original transcript files were intentionally not copied, moved, renamed, or overwritten when this project was built. The current database already contains the indexed transcript text, so the application works offline without source files.

For future updates on another computer, place only newly published canonical `.txt` transcript files in this folder and run `python update_database.py`. Existing database records are preserved. Alternatively, edit `config.json` so `transcript_directory` points to a sibling canonical transcript folder using a relative path.
