from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

BUILTIN = Path(__file__).resolve().parents[2] / 'resources' / 'skills'


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    source: str


def metadata(path: Path) -> dict:
    # Discovery reads frontmatter only, not every domain instruction body.
    with path.open(encoding='utf-8') as stream:
        if stream.readline().strip() != '---':
            raise ValueError('missing YAML frontmatter')
        header: list[str] = []
        for line in stream:
            if line.strip() == '---':
                break
            header.append(line)
            if sum(map(len, header)) > 8192:
                raise ValueError('frontmatter exceeds 8 KB')
        else:
            raise ValueError('unclosed frontmatter')
    value = yaml.safe_load(''.join(header))
    if not isinstance(value, dict):
        raise ValueError('frontmatter must be a mapping')
    name, description = value.get('name', ''), value.get('description', '')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
        raise ValueError('invalid skill name')
    if name != path.parent.name:
        raise ValueError('name must match directory')
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError('invalid skill description')
    return value


class SkillRegistry:
    def __init__(self, workspace: Path, *, trust_project: bool = False,
                 global_root: Path | None = None, builtin_root: Path = BUILTIN):
        self.workspace = workspace.resolve()
        self.skills: dict[str, Skill] = {}
        self.diagnostics: list[dict[str, str]] = []
        roots = [(builtin_root, 'built-in'),
                 (global_root or Path.home() / '.modai' / 'skills', 'global')]
        if trust_project:
            roots.append((self.workspace / '.modai' / 'skills', 'project'))
        elif (self.workspace / '.modai' / 'skills').exists():
            self.diagnostics.append({'verdict': 'WARN', 'detail': 'project skills ignored: workspace not trusted'})
        for root, source in roots:
            if not root.is_dir():
                continue
            resolved = root.resolve()
            if source == 'project' and not resolved.is_relative_to(self.workspace):
                self.diagnostics.append({'verdict': 'FAIL', 'detail': 'project skill root escapes workspace'})
                continue
            for path in sorted(root.glob('*/SKILL.md')):
                try:
                    if not path.resolve().is_relative_to(resolved):
                        raise ValueError('skill symlink escapes discovery root')
                    data = metadata(path)
                    name = data['name']
                    if name in self.skills:
                        self.diagnostics.append({'verdict': 'WARN', 'detail': f'{name}: {source} overrides {self.skills[name].source}'})
                    self.skills[name] = Skill(name, data['description'].strip(), path.resolve(), source)
                except (OSError, ValueError, yaml.YAMLError) as exc:
                    self.diagnostics.append({'verdict': 'FAIL', 'detail': f'{path.parent.name}: {exc}'})

    def catalog(self) -> str:
        return '<available_skills>\n' + '\n'.join(
            f'<skill name="{html.escape(s.name)}">{html.escape(s.description)}</skill>'
            for s in self.skills.values()) + '\n</available_skills>'

    def load(self, name: str, reference: str = '') -> tuple[str, str]:
        if name not in self.skills:
            raise ValueError(f'Unknown skill: {name}')
        skill = self.skills[name]
        metadata(skill.path)  # edits are revalidated at load time
        target = skill.path if not reference else (skill.path.parent / reference).resolve()
        if not target.is_relative_to(skill.path.parent) or not target.is_file():
            raise ValueError('skill reference escapes skill directory or is missing')
        if target.stat().st_size > 16000:
            raise ValueError('skill resource exceeds 16 KB; split into focused references')
        text = target.read_text(encoding='utf-8')
        return text, hashlib.sha256(text.encode()).hexdigest()

    def report(self) -> dict:
        return {'count': len(self.skills), 'skills': [{'name': s.name, 'source': s.source,
                'location': str(s.path)} for s in self.skills.values()], 'diagnostics': self.diagnostics}
