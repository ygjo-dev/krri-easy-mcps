import type { SkillCard, SkillInfoUpdate, SkillSuggestion } from '../types/api'

// 공유 정보 편집 칸. 목록 칸(태그 · 할 수 있는 일 · 사용 예시)은 화면에서 글자로 다루고 저장할 때 나눈다.
export interface InfoDraft {
  title: string
  summary: string
  tags: string
  useCases: string
  recommendedFor: string
  examplePrompts: string
  version: string
  author: string
}

export function draftFromSuggestion(s: SkillSuggestion, pkg: { version: string; author: string }): InfoDraft {
  return {
    title: s.title,
    summary: s.summary,
    tags: s.tags.join(', '),
    useCases: s.use_cases.join('\n'),
    recommendedFor: s.recommended_for,
    examplePrompts: s.example_prompts.join('\n'),
    version: pkg.version,
    author: pkg.author,
  }
}

export function draftFromSkill(skill: SkillCard): InfoDraft {
  return {
    title: skill.title,
    summary: skill.summary ?? '',
    tags: skill.tags.join(', '),
    useCases: skill.use_cases.join('\n'),
    recommendedFor: skill.recommended_for ?? '',
    examplePrompts: skill.example_prompts.join('\n'),
    version: skill.version,
    author: skill.author,
  }
}

const lines = (value: string) => value.split('\n').map((v) => v.trim()).filter(Boolean)
export const splitTags = (value: string) => value.split(',').map((t) => t.trim().replace(/^#+/, '').trim()).filter(Boolean)

export function draftToUpdate(d: InfoDraft): Required<Omit<SkillInfoUpdate, 'enrichment_source'>> {
  return {
    title: d.title.trim(),
    version: d.version.trim(),
    author: d.author.trim(),
    tags: splitTags(d.tags),
    summary: d.summary.trim(),
    use_cases: lines(d.useCases),
    recommended_for: d.recommendedFor.trim(),
    example_prompts: lines(d.examplePrompts),
  }
}
