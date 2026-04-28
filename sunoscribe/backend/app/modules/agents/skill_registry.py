from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .types import AgentSkill, AgentSkillContext


class AgentSkillRegistry:
    """Allowlisted reader for local agent skill documents."""

    ALLOWED_SKILLS = frozenset(
        {
            "mir-transcription",
            "score-ir-editing",
            "debug-diagnosis",
            "rvc-cover",
        }
    )
    PROFILE_SKILLS = {
        "diagnosis": ("mir-transcription", "debug-diagnosis"),
        "score_patch": ("score-ir-editing",),
        "rvc": ("rvc-cover",),
    }

    def __init__(
        self,
        skills_root: str | Path | None = None,
        allowed_skills: Iterable[str] | None = None,
    ) -> None:
        default_root = Path(__file__).resolve().parents[4] / "skills"
        self.skills_root = Path(skills_root or default_root).expanduser().resolve()
        self.allowed_skills = frozenset(
            self._normalize_allowed_name(name)
            for name in (allowed_skills or self.ALLOWED_SKILLS)
        )

    def read_skill(self, skill_name: str) -> AgentSkill:
        name = self._normalize_skill_name(skill_name)
        skill_dir = (self.skills_root / name).resolve()
        self._assert_inside_root(skill_dir)

        skill_path = (skill_dir / "SKILL.md").resolve()
        self._assert_inside_root(skill_path)
        if not skill_path.exists() or not skill_path.is_file():
            raise ValueError(f"allowed agent skill is missing: {name}")

        agent_config_path = (skill_dir / "agents" / "openai.yaml").resolve()
        agent_config_content: str | None = None
        agent_config_path_text: str | None = None
        if agent_config_path.exists() and agent_config_path.is_file():
            self._assert_inside_root(agent_config_path)
            agent_config_content = agent_config_path.read_text(encoding="utf-8")
            agent_config_path_text = str(agent_config_path)

        content = skill_path.read_text(encoding="utf-8")
        return AgentSkill(
            name=name,
            description=self._extract_description(content),
            path=str(skill_path),
            content=content,
            agent_config_path=agent_config_path_text,
            agent_config_content=agent_config_content,
        )

    def read_skill_context(self, skill_names: Iterable[str]) -> AgentSkillContext:
        skills: list[AgentSkill] = []
        warnings: list[str] = []
        for raw_name in skill_names:
            try:
                skills.append(self.read_skill(str(raw_name)))
            except Exception as exc:
                warnings.append(f"agent_skill_unavailable:{self._safe_name(raw_name)}:{type(exc).__name__}")
        return AgentSkillContext(skills=skills, warnings=warnings)

    def context_for_profile(self, profile: str) -> AgentSkillContext:
        names = self.PROFILE_SKILLS.get(str(profile or "").strip().lower())
        if not names:
            return AgentSkillContext(warnings=[f"unknown_agent_skill_profile:{self._safe_name(profile)}"])
        return self.read_skill_context(names)

    def _normalize_skill_name(self, raw_name: str) -> str:
        name = self._normalize_allowed_name(raw_name)
        if name not in self.allowed_skills:
            raise ValueError(f"agent skill is not allowlisted: {self._safe_name(raw_name)}")
        return name

    @staticmethod
    def _normalize_allowed_name(raw_name: str) -> str:
        name = str(raw_name or "").strip().lower()
        if not name:
            raise ValueError("agent skill name is empty")
        if Path(name).is_absolute() or "/" in name or "\\" in name or ".." in name:
            raise ValueError("agent skill name must be a simple allowlisted name")
        return name

    def _assert_inside_root(self, path: Path) -> None:
        try:
            path.relative_to(self.skills_root)
        except ValueError as exc:
            raise ValueError("agent skill path escaped the configured skills root") from exc

    @staticmethod
    def _extract_description(content: str) -> str | None:
        in_frontmatter = False
        for line in str(content or "").splitlines()[:40]:
            stripped = line.strip()
            if stripped == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter and stripped.startswith("description:"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
        return None

    @staticmethod
    def _safe_name(raw_name: object) -> str:
        text = str(raw_name or "").strip().replace("\\", "/")
        text = text.rsplit("/", 1)[-1]
        return text[:80] or "unknown"


SkillRegistry = AgentSkillRegistry
