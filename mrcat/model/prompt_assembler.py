"""Text assembly for optional tool-side interpretation; no workflow state."""
from dataclasses import dataclass
from pathlib import Path
import json
@dataclass
class PromptPackage:
    role_name: str
    stage: str
    system_prompt: str
    user_prompt: str
    context_digest: str = ""
class PromptAssembler:
    def __init__(self, *, prompt_dir=None, **kwargs):
        self.prompt_dir = Path(prompt_dir or Path(__file__).resolve().parent.parent / "prompts")
    def build_structured_prompt(self, *, role_name, stage, sections):
        path = self.prompt_dir / f"{role_name}.{stage}.system.md"
        return PromptPackage(role_name, stage, path.read_text(), "\n\n".join(f"## {key}\n{value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,default=str)}" for key,value in sections.items()))
