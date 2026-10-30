"""Balanced model routing: heavy authoring roles use strong; everyone else stays cheap."""


def test_strong_roles_use_strong_others_cheap(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("FORCE_CHEAP", "true")
    monkeypatch.setenv("STRONG_ROLES", "design,expdesign,protocol")
    monkeypatch.setenv("OPENAI_STRONG_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_CHEAP_MODEL", "gpt-4o-mini")
    for k in ("PROTOCOL_MODEL", "DESIGN_MODEL", "EXPDESIGN_MODEL", "SUMMARY_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from agents.protocol_agent import ProtocolAgent
    from agents.experiment_design_agent import ExperimentDesignAgent
    from agents.summary_agent import SummaryAgent
    from agents.fill_agent import FillAgent
    assert ProtocolAgent().model == "gpt-4o"            # heavy -> strong
    assert ExperimentDesignAgent().model == "gpt-4o"    # heavy -> strong
    assert SummaryAgent().model == "gpt-4o-mini"        # light -> cheap
    monkeypatch.setenv("FILL_PROVIDER", "openai")
    assert FillAgent().model == "gpt-4o-mini"           # not in STRONG_ROLES -> cheap


def test_explicit_role_model_still_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("FORCE_CHEAP", "true")
    monkeypatch.setenv("STRONG_ROLES", "protocol")
    monkeypatch.setenv("PROTOCOL_MODEL", "gpt-4o-mini")   # explicit pin overrides STRONG_ROLES
    from agents.protocol_agent import ProtocolAgent
    assert ProtocolAgent().model == "gpt-4o-mini"
