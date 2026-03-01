from bpg.packaging.spec import EnvVarSpec, PackageResult


def test_env_var_spec_required_flag_and_default():
    spec = EnvVarSpec(name="DB_URL", required=True, value="postgres://x")
    assert spec.required is True
    assert spec.value == "postgres://x"


def test_package_result_ready_to_run_false_when_unresolved():
    result = PackageResult(output_dir="/tmp/out", unresolved_required_vars=["DB_URL"])
    assert result.ready_to_run is False
