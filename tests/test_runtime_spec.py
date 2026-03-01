from bpg.packaging.runtime_spec import RuntimeSpec
from bpg.packaging.spec import EnvVarSpec


def test_runtime_spec_tracks_services_env_and_readiness_requirements():
    spec = RuntimeSpec(
        process_name="p1",
        process_hash="abc",
        mode="local",
        ledger_backend="sqlite-file",
        runtime_image="bpg-local:dev",
        dashboard_enabled=True,
        dashboard_port=9090,
        services=["postgres"],
        env_vars=[
            EnvVarSpec(name="API_KEY", required=True, value=None),
            EnvVarSpec(name="OPTIONAL", required=False, value=None),
        ],
    )
    assert spec.process_name == "p1"
    assert spec.runtime_image == "bpg-local:dev"
    assert spec.dashboard_enabled is True
    assert spec.dashboard_port == 9090
    assert "postgres" in spec.services
    assert spec.required_env == ["API_KEY"]
    assert spec.unresolved_required_env == ["API_KEY"]
    assert spec.ready_to_run is False
