"""Display projection must not rewrite provider replay or canonical messages."""
import copy
import sys
import types
from types import SimpleNamespace

from api import streaming


def test_settlement_projects_commentary_without_mutating_history(monkeypatch):
    messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "one"}],
                 "codex_message_items": [{"type": "message", "role": "assistant",
                     "phase": "commentary", "content": [{"type": "output_text", "text": "Checking."}]}]}]
    original = copy.deepcopy(messages)
    calls = []

    def project(rows, *, home):
        calls.append(home)
        return [dict(row, display_commentary=["Checking."], display_reasoning="") for row in rows]

    monkeypatch.setitem(sys.modules, "agent.history_commentary", types.SimpleNamespace(project_history_commentary=project))
    from api import profiles
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda name: "isolated/" + name)
    session = SimpleNamespace(messages=messages, profile="example", compact=lambda: {})
    payload = streaming._session_payload_with_full_messages(session)
    assert payload["messages"][0].get("display_commentary") == ["Checking."]
    assert calls == ["isolated/example"]
    assert messages == original
    assert payload["messages"][0]["content"] == ""
    assert payload["messages"][0]["codex_message_items"] == original[0]["codex_message_items"]

def test_hydrated_scene_recovers_projected_commentary_before_tools():
    from api import routes
    messages = [
        {"role": "user", "content": "Check both"},
        {"role": "assistant", "content": "", "display_commentary": ["Checking one."],
         "display_reasoning": "Inspect the component.",
         "tool_calls": [{"id": "one", "function": {"name": "terminal", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "one", "content": "ok"},
        {"role": "assistant", "content": "Done.", "display_commentary": ["Verifying results."]},
    ]
    original = copy.deepcopy(messages)
    scene = routes._complete_hydrated_anchor_scene(messages, {"activity_rows": []}, 3)
    rows = scene["activity_rows"]
    assert [r["text"] for r in rows if r["role"] == "prose"] == ["Checking one.", "Verifying results."]
    assert [r["role"] for r in rows] == ["thinking", "prose", "tool", "prose"]
    assert scene["final_answer"] == "Done."
    assert messages == original


def test_optional_projection_failure_does_not_break_payload(monkeypatch):
    from api.history_display import project_history_for_display
    from api import profiles
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda name: "isolated")
    def broken(*args, **kwargs):
        raise TypeError("incompatible optional helper")
    monkeypatch.setitem(sys.modules, "agent.history_commentary", types.SimpleNamespace(project_history_commentary=broken))
    source=[{"role":"assistant", "content":"Done.", "codex_message_items":[{}],
             "display_commentary":["Stale imported projection"]}]
    out=project_history_for_display(source)
    assert out==[{"role":"assistant", "content":"Done.", "codex_message_items":[{}]}]
    assert source[0]["display_commentary"]==["Stale imported projection"]


def test_optional_projection_rejects_changed_row_alignment(monkeypatch):
    from api.history_display import project_history_for_display
    from api import profiles
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda name: "isolated")
    source=[{"role":"assistant", "content":"Done.", "codex_message_items":[{}]}]
    for value in (None, [], [{"role":"assistant", "content":"Changed."}]):
        monkeypatch.setitem(sys.modules, "agent.history_commentary", types.SimpleNamespace(project_history_commentary=lambda rows, home, value=value:value))
        assert project_history_for_display(source)==source


def test_absent_projection_retains_canonical_fields(monkeypatch):
    from api.history_display import project_history_for_display
    monkeypatch.setitem(sys.modules, "agent.history_commentary", None)
    source=[{"role":"assistant", "content":"Done.", "codex_message_items":[{}]}]
    assert project_history_for_display(source)==source


def test_real_agent_projection_on_settlement_payload(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("agent.history_commentary", reason="optional modern agent API")
    from api import profiles
    (tmp_path/"config.yaml").write_text("display:\n  show_commentary: true\n  interim_assistant_messages: true\n")
    monkeypatch.setattr(profiles,"get_hermes_home_for_profile",lambda name:tmp_path)
    messages=[{"role":"assistant","content":"Done.","reasoning":"Checking.\n\nPrivate thought.",
               "codex_message_items":[{"type":"message","role":"assistant","phase":"commentary",
               "content":[{"type":"output_text","text":"Checking."}]}]}]
    original=copy.deepcopy(messages)
    session=SimpleNamespace(messages=messages,profile="example",compact=lambda:{})
    payload=streaming._session_payload_with_full_messages(session)
    assert payload["messages"][0]["display_commentary"]==["Checking."]
    assert payload["messages"][0]["display_reasoning"]=="Private thought."
    assert messages==original


def test_empty_projected_reasoning_keeps_unconsumed_thinking():
    from api import routes
    assert routes._anchor_scene_message_reasoning_text({"display_reasoning":"", "thinking":"Other thought"})=="Other thought"
    assert routes._anchor_scene_message_reasoning_text({"display_reasoning":"", "reasoning":"Public commentary"})==""



def test_steering_input_keeps_existing_scene_ownership():
    from api import routes
    messages=[{"role":"user","content":"Check"},
              {"role":"assistant","content":"","timestamp":2,"display_commentary":["Checking A."]},
              {"role":"user","content":"Also B.","display_kind":"steer"},
              {"role":"assistant","content":"Done.","timestamp":4,"display_commentary":["Checking B."]}]
    scene={"activity_rows":[{"role":"prose","text":"Checking A.","row_id":"live-a"}]}
    result=routes._complete_hydrated_anchor_scene(messages,scene,3)
    assert result["identity"]["source_message_refs"]==[
        routes._assistant_anchor_scene_message_ref(messages[1]),
        routes._assistant_anchor_scene_message_ref(messages[3]),
    ]
    assert [r["text"] for r in result["activity_rows"] if r["role"]=="prose"]==["Checking A.","Checking B."]



def test_equal_commentary_from_distinct_messages_is_not_lost():
    from api import routes
    messages=[{"role":"user","content":"Check"},
              {"role":"assistant","content":"","timestamp":2,"display_commentary":["Checking."]},
              {"role":"assistant","content":"","timestamp":3,"display_commentary":["Checking."]},
              {"role":"assistant","content":"Done.","timestamp":4}]
    scene={"activity_rows":[{"role":"prose","text":"Checking.","row_id":"live-a","source_event_type":"interim_assistant"}]}
    result=routes._complete_hydrated_anchor_scene(messages,scene,3)
    prose=[r for r in result["activity_rows"] if r["role"]=="prose"]
    assert [r["text"] for r in prose]==["Checking.","Checking."]
    assert [r["group"]["assistant_msg_idx"] for r in prose]==[1,2]


def test_joined_live_commentary_is_replaced_by_its_projected_items():
    from api import routes
    messages=[{"role":"user","content":"Check"},
              {"role":"assistant","content":"","display_commentary":["Checking one.","Checking two."]},
              {"role":"assistant","content":"Done."}]
    scene={"activity_rows":[{"role":"prose","text":"Checking one.\n\nChecking two.","row_id":"live-a","source_event_type":"interim_assistant"}]}
    result=routes._complete_hydrated_anchor_scene(messages,scene,2)
    assert [r["text"] for r in result["activity_rows"] if r["role"]=="prose"]==["Checking one.","Checking two."]


def test_incomplete_saved_trace_does_not_hide_complete_commentary():
    from api import routes
    messages=[{"role":"user","content":"Check"},
              {"role":"assistant","content":"","display_commentary":["Checking the component carefully."]},
              {"role":"assistant","content":"Done."}]
    scene={"activity_rows":[{"role":"prose","text":"Checking the comp","row_id":"partial-live","source_event_type":"token"}]}
    result=routes._complete_hydrated_anchor_scene(messages,scene,2)
    prose=[r["text"] for r in result["activity_rows"] if r["role"]=="prose"]
    assert "Checking the component carefully." in prose
    assert "Checking the comp" in prose  # no guessed deletion without provenance
    assert "Done." not in prose


def test_projection_cannot_mutate_nested_canonical_items(monkeypatch):
    import sys
    import types
    from api.history_display import project_history_for_display
    original=[{"role":"assistant","content":"","codex_message_items":[{"text":"original"}]}]
    def mutate(rows, **kwargs):
        rows[0]["codex_message_items"][0]["text"]="changed"
        return rows
    monkeypatch.setitem(sys.modules,"agent.history_commentary",types.SimpleNamespace(project_history_commentary=mutate))
    assert project_history_for_display(original)==original
    assert original[0]["codex_message_items"][0]["text"]=="original"
