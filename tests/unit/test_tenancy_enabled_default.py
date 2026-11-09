from verifund_control_plane.settings import Settings

def test_tenancy_enabled_defaults_to_true():
    s = Settings(_env_file=None, mode="fake")
    assert s.tenancy_enabled is True

def test_tenancy_enabled_env_false_disables():
    import os
    os.environ["VERIFUND_TENANCY_ENABLED"] = "false"
    s = Settings(_env_file=None, mode="fake")
    del os.environ["VERIFUND_TENANCY_ENABLED"]
    assert s.tenancy_enabled is False
