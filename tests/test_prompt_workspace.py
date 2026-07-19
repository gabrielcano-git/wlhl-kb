import json

from prompt_workspace import (
    DEFAULT_SETTINGS,
    add_history,
    assemble_prompt,
    clear_history,
    get_settings,
    list_history,
    list_presets,
    load_episode_material,
    save_preset,
    save_settings,
    validate_settings_import,
)


def test_schema_settings_presets_history_and_prompt_generation(wlhl_db):
    settings = get_settings(wlhl_db)
    assert settings["master_prompt"] == DEFAULT_SETTINGS["master_prompt"]
    settings["preferred_language"] = "Clear\nPractical"
    save_settings(wlhl_db, settings)
    assert get_settings(wlhl_db)["preferred_language"] == "Clear\nPractical"

    save_preset(wlhl_db, "Test preset", "newsletter", {"topic": "maintenance"}, [1])
    assert list_presets(wlhl_db)[0]["name"] == "Test preset"
    material = load_episode_material(wlhl_db, 1, "weight", "Database fields plus relevant transcript excerpts")
    prompt = assemble_prompt(settings, "newsletter", {"topic": "maintenance"}, [material])
    assert material["episode_id"] in prompt
    assert "maintenance" in prompt.lower()
    add_history(wlhl_db, "newsletter", "maintenance", [1], prompt, {"topic": "maintenance"})
    assert len(list_history(wlhl_db)) == 1
    clear_history(wlhl_db)
    assert list_history(wlhl_db) == []


def test_settings_import_validation():
    loaded = validate_settings_import({"preferred_language": "Human", "unknown": "ignored"})
    assert loaded["preferred_language"] == "Human"
    assert "unknown" not in loaded
    try:
        validate_settings_import({"preferred_language": []})
    except ValueError as error:
        assert "must be text" in str(error)
    else:
        raise AssertionError("invalid settings were accepted")
