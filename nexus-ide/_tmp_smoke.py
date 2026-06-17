from backend.agents.base import AgentBase, AgentAction


class TestAgent(AgentBase):
    name = "TEST"
    model_key = "micro"
    prompt_file = "router"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.WRITE_FILE,
        AgentAction.WRITE_FILE_ABSOLUTE,
    }

    async def _execute(self, request):
        yield ""


a = TestAgent()
instr = a._build_tool_instructions()
for line in instr.splitlines():
    if line.startswith("  - "):
        print(line)
print("---DONE---")
