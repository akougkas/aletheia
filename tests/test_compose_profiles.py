from aletheia.compose import COMPOSE_FILE, compose_plan


def test_compose_plan_core_only():
    plan = compose_plan()
    assert plan.files == [COMPOSE_FILE]
    assert plan.profiles == []
    assert plan.command == ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d"]


def test_compose_plan_with_ollama_profile():
    plan = compose_plan(profiles=["ollama"])
    assert plan.profiles == ["ollama"]
    assert plan.command == [
        "docker", "compose", "-f", COMPOSE_FILE,
        "--profile", "ollama",
        "up", "-d",
    ]


def test_compose_plan_with_gpu_profile():
    plan = compose_plan(profiles=["gpu"])
    assert plan.profiles == ["gpu"]
    assert "--profile" in plan.command
    assert "gpu" in plan.command


def test_compose_plan_down_action():
    plan = compose_plan(action="down")
    assert plan.command == ["docker", "compose", "-f", COMPOSE_FILE, "down"]


def test_compose_plan_no_detach():
    plan = compose_plan(detach=False)
    assert "-d" not in plan.command
