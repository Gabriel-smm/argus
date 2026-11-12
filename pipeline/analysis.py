"""One Laya run over uploaded observations, sharing the GPU with Ollama."""

from pipeline.inputs import InputError
from pipeline.lookup import check_all
from pipeline.ollama import unload, warmup


class OllamaError(RuntimeError):
    """Ollama could not be reached to free or reclaim the GPU."""


def run(questions, observations):
    """Answer every question for every observation, in input order."""
    # Laya and the Ollama model do not both fit on a small GPU, so they take turns.
    try:
        unload()
    except SystemExit as exc:
        raise OllamaError(str(exc)) from exc
    # Imported here so the service starts, and its tests run, without loading torch.
    from pipeline.laya import classify, describe, load_agent, release

    agent = None
    try:
        agent = load_agent()
        answers = classify(agent, observations, questions)
    except SystemExit as exc:
        # Laya's only refusal is a question too long for its budget.
        raise InputError("knowledge", str(exc)) from exc
    finally:
        if agent is not None:
            release(agent)
        try:
            warmup()
        except SystemExit as exc:
            raise OllamaError(str(exc)) from exc
    # The site check needs no GPU: plain rules over the files in data/context/.
    lookups = check_all(observations)
    return [
        {"id": observation["id"], "state": describe(observation), "answers": answer, "lookup": lookup}
        for observation, answer, lookup in zip(observations, answers, lookups)
    ]
