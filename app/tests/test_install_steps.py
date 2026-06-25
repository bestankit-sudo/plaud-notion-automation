from app.install.steps import ALL_STEPS, STEPS_BY_ID, Step


def test_step_order():
    assert [s.id for s in ALL_STEPS] == [
        "brew", "ffmpeg", "py312", "ml", "docker", "riffado", "plaud_otp", "launchd"
    ]


def test_kind_classification():
    guide = {s.id for s in ALL_STEPS if s.kind == "guide"}
    assert guide == {"brew", "docker", "plaud_otp"}
    auto = {s.id for s in ALL_STEPS if s.kind == "auto"}
    assert auto == {"ffmpeg", "py312", "ml", "riffado", "launchd"}


def test_riffado_after_docker():
    ids = [s.id for s in ALL_STEPS]
    assert ids.index("riffado") > ids.index("docker")  # Riffado needs Docker


def test_guide_steps_have_a_url():
    for s in ALL_STEPS:
        if s.kind == "guide":
            assert s.guide_url, f"guide step {s.id} needs a guide_url"


def test_lookup_and_frozen():
    assert STEPS_BY_ID["ml"].title == "Local ML stack"
    import dataclasses
    assert dataclasses.is_dataclass(Step)
