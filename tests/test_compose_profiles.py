from aletheia.compose import (
    CORE_COMPOSE_FILE,
    CRAWLER_COMPOSE_FILE,
    LOCAL_OLLAMA_COMPOSE_FILE,
    compose_file_stack,
    compose_plan,
)


def test_compose_file_stack_core_only():
    assert compose_file_stack() == [CORE_COMPOSE_FILE]


def test_compose_file_stack_with_all_layers():
    assert compose_file_stack(include_crawler=True, include_local_ollama=True) == [
        CORE_COMPOSE_FILE,
        CRAWLER_COMPOSE_FILE,
        LOCAL_OLLAMA_COMPOSE_FILE,
    ]


def test_compose_plan_command_for_up_detached():
    plan = compose_plan(include_crawler=True, include_local_ollama=False)
    assert plan.files == [CORE_COMPOSE_FILE, CRAWLER_COMPOSE_FILE]
    assert plan.command == [
        "docker",
        "compose",
        "-f",
        CORE_COMPOSE_FILE,
        "-f",
        CRAWLER_COMPOSE_FILE,
        "up",
        "-d",
    ]
