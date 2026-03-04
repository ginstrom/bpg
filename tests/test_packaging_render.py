from bpg.packaging.render import render_compose, render_env
from bpg.packaging.runtime_spec import RuntimeSpec
from bpg.packaging.spec import EnvVarSpec


def test_render_env_uses_required_sentinel_for_missing_required():
    text = render_env(
        [
            EnvVarSpec(name="API_KEY", required=True, value=None),
        ]
    )
    assert "API_KEY=__REQUIRED__" in text


def test_render_compose_only_includes_inferred_services():
    spec = RuntimeSpec(
        process_name="p1",
        process_hash="abc",
        mode="package",
        ledger_backend="postgres",
        runtime_image="ghcr.io/example/bpg:latest",
        services=["postgres"],
        env_vars=[],
    )
    compose = render_compose(spec)
    assert "postgres:" in compose
    assert "redis:" not in compose


def test_render_compose_includes_dashboard_service_when_enabled():
    spec = RuntimeSpec(
        process_name="p1",
        process_hash="abc",
        mode="package",
        ledger_backend="postgres",
        runtime_image="ghcr.io/example/bpg:latest",
        dashboard_enabled=True,
        dashboard_port=9090,
        services=["dashboard", "postgres"],
        env_vars=[],
    )
    compose = render_compose(spec)
    assert "dashboard:" in compose
    assert "entrypoint:" in compose
    assert "-m" in compose
    assert "9090:9090" in compose
    assert "BPG_PROCESS_FILE" in compose
    assert "profiles:" in compose
    assert "runner" in compose


def test_render_compose_uses_local_runtime_image_in_local_mode():
    spec = RuntimeSpec(
        process_name="p1",
        process_hash="abc",
        mode="local",
        ledger_backend="sqlite-file",
        runtime_image="bpg-local:dev",
        services=[],
        env_vars=[],
    )
    compose = render_compose(spec)
    assert "bpg-local:dev" in compose
    assert "user:" in compose
    assert "BPG_RUNTIME_UID" in compose
    assert "BPG_RUNTIME_GID" in compose
    assert "run" in compose
    assert "p1" in compose


def test_render_compose_builds_locally_in_package_mode_by_default():
    spec = RuntimeSpec(
        process_name="p1",
        process_hash="abc",
        mode="package",
        ledger_backend="postgres",
        runtime_image="bpg-package:local",
        package_local_build=True,
        services=["postgres"],
        env_vars=[],
    )
    compose = render_compose(spec)
    assert "build:" in compose
    assert "context: ." in compose
    assert "dockerfile: Dockerfile" in compose
    assert "user:" in compose
