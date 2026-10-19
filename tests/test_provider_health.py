"""Configuration alone cannot establish model readiness."""


def test_configured_provider_is_unverified_until_every_required_role_succeeds():
    from runtime_support.provider_health import ProbeState
    state = ProbeState()
    assert state.describe("config-a", {"parse", "generate"}, configured=True)["status"] == "configured"
    state.record("config-a", "parse", True, "local-model")
    assert state.describe("config-a", {"parse", "generate"}, configured=True)["status"] == "configured"
    state.record("config-a", "generate", True, "local-model")
    result = state.describe("config-a", {"parse", "generate"}, configured=True)
    assert result["status"] == "ok" and result["verified_at"]


def test_failure_expiry_and_reconfiguration_remove_verified_readiness():
    from runtime_support.provider_health import ProbeState
    clock = [0.0]
    state = ProbeState(clock=lambda: clock[0])
    state.record("config-a", "generate", True, "local-model")
    assert state.describe("config-a", {"generate"}, configured=True, ttl_s=10)["status"] == "ok"
    clock[0] = 11.0
    assert state.describe("config-a", {"generate"}, configured=True, ttl_s=10)["status"] == "configured"
    assert state.describe("config-b", {"generate"}, configured=True)["status"] == "configured"
    state.record("config-a", "generate", False, "local-model", error="ValidationError")
    assert state.describe("config-a", {"generate"}, configured=True)["status"] == "degraded"
    assert state.describe("config-a", {"generate"}, configured=False)["status"] == "off"
