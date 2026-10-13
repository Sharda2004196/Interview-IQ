"""ADK entrypoint — thin wiring only. `adk web` discovers `root_agent` here.

Agent definitions live in the agents/ subpackage: interviewer,
question_generator, evaluator, config. FunctionTools will live in tools/.
"""

from .agents.interviewer import root_agent

__all__ = ["root_agent"]
