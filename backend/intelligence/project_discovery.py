"""
backend/intelligence/project_discovery.py

Project discovery and inference engine for HINAKU conversations.
Identifies whether a conversational exchange relates to an existing project or introduces a new candidate project.
"""

import re
from typing import List, Optional, Tuple

from .project_types import (
    ProjectDiscoveryCandidate,
    ProjectRecord,
    ProjectStatus,
)

# Common conversational trigger patterns for project declarations
PROJECT_DECLARATION_PATTERNS = [
    re.compile(
        r"""(?ix)
        \b(?:working\s+on|building|developing|starting|created)\s+(?:a|the)?\s*project\s+(?:called|named|known\s+as)?\s*
        (?:
            ["'](?P<quoted>[^"']{2,50})["']
            |
            (?P<unquoted>[a-zA-Z0-9_\-\.]+)(?:\s+[a-zA-Z0-9_\-\.]+)?(?=\s+(?:for|to|that|which|with|using|in|at|and|\.|\,|$)|$)
        )
        """
    ),
    re.compile(
        r"""(?ix)
        \bproject\s*:\s*
        (?:
            ["'](?P<quoted>[^"']{2,50})["']
            |
            (?P<unquoted>[a-zA-Z0-9_\-\.]+)(?:\s+[a-zA-Z0-9_\-\.]+)?(?=\s+(?:for|to|that|which|with|using|in|at|and|\.|\,|$)|$)
        )
        """
    ),
    re.compile(r"(?i)\b(?:in|for)\s+(?:the\s+)?([a-zA-Z0-9_\-\.]{2,30})\s+(?:repo|repository|codebase|project)\b"),
    re.compile(
        r"""(?ix)
        \b(?:new\s+project)\s*
        (?:
            ["'](?P<quoted>[^"']{2,50})["']
            |
            (?P<unquoted>[a-zA-Z0-9_\-\.]+)(?:\s+[a-zA-Z0-9_\-\.]+)?(?=\s+(?:for|to|that|which|with|using|in|at|and|\.|\,|$)|$)
        )
        """
    ),
]


class ProjectDiscovery:
    """Detects, matches, and infers project contexts from conversational interactions."""

    @classmethod
    def analyze_conversation(
        cls,
        text: str,
        existing_projects: List[ProjectRecord],
    ) -> Optional[ProjectDiscoveryCandidate]:
        """
        Analyzes conversation text to match against existing registered projects
        or detect a potential new project.
        """
        if not text or not text.strip():
            return None

        clean_text = text.strip()

        # Step 1: Check matches against existing projects (highest priority)
        matched_candidate = cls._match_existing_project(clean_text, existing_projects)
        if matched_candidate:
            return matched_candidate

        # Step 2: Check for candidate new project declarations
        new_project_candidate = cls._detect_new_project_candidate(clean_text)
        return new_project_candidate

    @classmethod
    def _match_existing_project(
        cls,
        text: str,
        projects: List[ProjectRecord],
    ) -> Optional[ProjectDiscoveryCandidate]:
        """Compares text against names, IDs, tech stacks, and keywords of existing projects."""
        best_match: Optional[ProjectRecord] = None
        best_confidence: float = 0.0
        evidence_terms: List[str] = []
        matching_count = 0

        for p in projects:
            score = 0.0
            terms: List[str] = []

            # Exact project_id match (case-insensitive word boundary)
            if re.search(rf"(?i)\b{re.escape(p.project_id)}\b", text):
                score += 0.8
                terms.append(f"id:{p.project_id}")

            # Exact project name match
            if re.search(rf"(?i)\b{re.escape(p.name)}\b", text):
                score += 0.85
                terms.append(f"name:{p.name}")

            # Tech stack keyword overlap
            matched_tech = [t for t in p.tech_stack if re.search(rf"(?i)\b{re.escape(t)}\b", text)]
            if matched_tech:
                score += min(0.3, len(matched_tech) * 0.1)
                terms.extend([f"tech:{t}" for t in matched_tech])

            # Purpose / description keywords match
            if p.purpose:
                purpose_words = [w for w in p.purpose.lower().split() if len(w) > 4]
                matched_purpose = [w for w in purpose_words if re.search(rf"(?i)\b{re.escape(w)}\b", text)]
                if matched_purpose:
                    score += min(0.2, len(matched_purpose) * 0.05)

            score = min(1.0, score)

            if score > 0.4:
                matching_count += 1
                if score > best_confidence:
                    best_confidence = score
                    best_match = p
                    evidence_terms = terms

        if not best_match:
            return None

        # If multiple projects match closely, flag ambiguity
        needs_confirmation = (matching_count > 1) or (best_confidence < 0.8)

        return ProjectDiscoveryCandidate(
            candidate_name=best_match.name,
            matched_project_id=best_match.project_id,
            confidence=round(best_confidence, 2),
            is_new_project=False,
            evidence_terms=evidence_terms,
            suggested_purpose=best_match.purpose,
            needs_owner_confirmation=needs_confirmation,
        )

    @classmethod
    def _detect_new_project_candidate(cls, text: str) -> Optional[ProjectDiscoveryCandidate]:
        """Detects explicit new project declarations in conversational prompts."""
        for pattern in PROJECT_DECLARATION_PATTERNS:
            match = pattern.search(text)
            if match:
                groups = match.groupdict()
                if groups.get("quoted"):
                    raw_name = groups["quoted"].strip()
                elif groups.get("unquoted"):
                    raw_name = groups["unquoted"].strip()
                else:
                    raw_name = match.group(1).strip()

                # Clean up prepositions or punctuation
                candidate_name = re.split(r"(?i)\s+(?:for|to|that|which|with|using|in|at|and)\s+", raw_name)[0]
                candidate_name = candidate_name.rstrip(".,;:?!- ")
                if len(candidate_name) < 2:
                    continue

                # Owner explicitly using "building project X" has moderate-to-high confidence
                confidence = 0.75
                # Requires confirmation before becoming a permanent active project
                return ProjectDiscoveryCandidate(
                    candidate_name=candidate_name,
                    matched_project_id=None,
                    confidence=confidence,
                    is_new_project=True,
                    evidence_terms=[match.group(0)],
                    suggested_purpose="Inferred from conversation",
                    needs_owner_confirmation=True,
                )

        return None
