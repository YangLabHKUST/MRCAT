"""Frontmatter for planning; detailed guides are disclosed only when selected."""
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class Skill:
    id: str
    description: str
    skill_dir: Path
    instruction_body: str
    accepts: tuple[str, ...] = ()
    produces: str = ''
    reusable_outputs: tuple[str, ...] = ()


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self._skills = {}
        for path in sorted(self.skills_dir.glob('*/SKILL.md')):
            text = path.read_text(encoding='utf-8')
            parts = text.split('---', 2)
            meta = (yaml.safe_load(parts[1]) or {}) if text.startswith('---') and len(parts) == 3 else {}
            self._skills[path.parent.name] = Skill(
                id=path.parent.name, description=str(meta.get('description', '')),
                skill_dir=path.parent, instruction_body=text,
                accepts=tuple(meta.get('accepts-milestones') or []),
                produces=str(meta.get('produces-milestone') or ''),
                reusable_outputs=tuple(meta.get('reusable-outputs') or []))

    def list_bundles(self):
        return list(self._skills.values())

    def get(self, skill_id):
        return self._skills.get(skill_id)

    def catalog(self):
        return '\n'.join(f"- {s.id}: {' '.join(s.description.split())}" for s in self.list_bundles())

    def planning_catalog(self):
        """These are planning hints, never executable dependencies or bindings."""
        return [dict(skill_id=s.id, description=s.description, accepts=list(s.accepts),
                     produces=s.produces, reusable_outputs=list(s.reusable_outputs))
                for s in self.list_bundles()]

    def read(self, skill_id):
        skill = self.get(skill_id)
        if skill is None:
            raise KeyError(f'Unknown guide: {skill_id}. You can still write code without a guide.')
        return skill.instruction_body
