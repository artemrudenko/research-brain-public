"""Digest chrome localization — the `delivery.language` string tables.

The digest's PROSE follows `delivery.language` on the agentic path (the LLM
writes it), but the deterministic CHROME — titles, section headers, trust
markers, footers — was hardcoded English, so a `language: ru` install got
Russian prose under an English skeleton every week. This module centralizes
those strings per language.

Contract:
- `en` is the reference table and MUST stay byte-identical to the historical
  wording (drift tests pin it) — localization changed nothing for en installs.
- An unknown language falls back to the full `en` chrome (never a mixed page,
  never a KeyError); a key missing from a translation falls back per-key.
- The RU TL;DR header deliberately keeps the literal "TL;DR" token:
  `scripts.delivery.email_html` styles the callout by that token.
- Quiet-week detection stays language-independent — it keys on the structural
  `QUIET_DIGEST_HTML_MARKER`, never on these strings (ADR 0016).
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Titles / quiet builds
        "weekly_title": "# 🧠 Weekly digest — {date}",
        "daily_title": "# 🗞 Daily digest — {date}",
        "quiet_week_title": "# Weekly digest — {date}",
        "quiet_day_title": "# Daily digest — {date}",
        "quiet_week_line": (
            "Quiet week — nothing new surfaced in the last {days} days. "
            "Everything's running fine; I'll have more for you in the next digest."
        ),
        "quiet_day_line": (
            "Quiet day — nothing new arrived in the last {days_phrase}. "
            "Everything's running fine; I'll have more for you in the next digest."
        ),
        # Section headers
        "tldr_header": "## ⚡ TL;DR",
        "new_sources_header": "## 📰 New sources (last {window})",
        "concepts_header": "## 💡 Updated concepts (last {days} days)",
        "synthesis_header": "## 🧪 Synthesis this week",
        "attention_header": "## 📌 Needs attention",
        "front_doors_header": "## 🗂 Vault front doors",
        "front_door_line": "- **{label}:** {count_phrase} in `{base_path}`.",
        # Labels / small lines
        "knowledge_base_label": "Knowledge base:",
        "reused_line": (
            "**🔁 Reused existing knowledge:** {count} existing concepts reused "
            "during synthesis."
        ),
        "ops_health_label": "**⚠️ System health:**",
        "kb_changes_line": (
            "**🧠 Knowledge base changes:** {created} concepts created, "
            "{updated} updated this run."
        ),
        "debut_topic_caveat": (
            "🌱 New topic — first week; the selection may be noisy until its "
            "include/exclude rules settle."
        ),
        "no_new_sources": "No new sources.",
        "no_concept_updates": "No concept updates.",
        "nothing_pending": "Nothing pending.",
        "collected_label": "collected",
        "more_by_credibility": "+{hidden} more — top {shown} shown by source credibility",
        "more_in_base": "+{hidden} more in `{base_path}`",
        # TL;DR entry headlines
        "tldr_most_active": "📰 Most active: **{topic}** ({share})",
        "tldr_share": "{count} of {total_phrase}",
        "tldr_only_topic": "📰 {count_phrase} in **{topic}**",
        "tldr_worth_a_look": "🔎 Worth a look: {titled}{marker}",
        "tldr_concepts_updated": "💡 {count_phrase} updated:",
        # Volume headline pieces
        "header_summary": "{sources_phrase} across {topics_phrase}, {concepts_phrase}.",
        "daily_header_summary": "{sources_phrase} across {topics_phrase}.",
        # Publisher markers (CONVENTIONS §16; multi-domain lines are composed in
        # scripts.corroborate.trust_line, which owns the count agreement)
        "trust_single": "🟡 One retained publisher domain — check the claim",
        # Front-door labels
        "front_door_lessons": "Lessons",
        "front_door_playbooks": "Playbooks",
        "front_door_active_note": "active note",
        "front_door_active_notes": "active notes",
        "front_door_reusable_method": "reusable method",
        "front_door_reusable_methods": "reusable methods",
        # Footers (build_digest)
        "footer_audience": (
            "_🎚 Audience level '{level}' is configured — agent-rendered digests "
            "and chat answers apply it; this deterministic (no-agent) build keeps "
            "its fixed wording (docs/audience-levels.md)._"
        ),
        "footer_feedback": (
            "_💬 Feedback tunes future digests — reply e.g. 'too technical', "
            "'simpler', 'less of <topic>', 'mute <source>' (docs/feedback.md)._"
        ),
        "footer_report": (
            "_📊 Full report: [{name}]({name}) — open in a browser for the tabbed "
            "view and the per-source audit._"
        ),
        # Glossary
        "glossary_heading": "## 📖 Glossary",
        # Trends section (scripts/trend_report/render.py)
        "trends_title": "📈 Trends — {date}",
        "trends_intro": "_Comparing the last {days} days with the {days} before._",
        "trends_volume_header": "📊 Topic volume (this week vs last)",
        "trends_volume_line": "**{topic}** — {current} this week ({arrow} {delta} vs last)",
        "trends_no_sources": "No new sources this week.",
        "trends_new_topics": "🌱 New topics: {topics}",
        "trends_fading_topics": "💤 Fading topics: {topics}",
        "trends_tags_header": "🏷 Rising tags",
        "trends_tag_line": "**{tag}** — {current} concept(s) updated ({arrow} {delta})",
        "trends_activity_header": "⚡ Activity",
        "trends_inflow_line": "Inflow: {current} this week ({arrow} {delta} vs last)",
        "trends_backlog_line": "Backlog: {backlog} collected source(s) not yet curated",
        "trends_growth_header": "🧠 Knowledge growth",
        "trends_created_line": "Concepts created: {current} this week ({arrow} {delta} vs last)",
        "trends_sparkline_line": "Created per week (last {weeks}w): {spark} ({first} → {last})",
        "trends_updated_line": "Concepts updated this week: {count}",
        "trends_connected_line": "Most connected: {pretty}",
    },
    "ru": {
        "weekly_title": "# 🧠 Еженедельный дайджест — {date}",
        "daily_title": "# 🗞 Дневной дайджест — {date}",
        "quiet_week_title": "# Еженедельный дайджест — {date}",
        "quiet_day_title": "# Дневной дайджест — {date}",
        "quiet_week_line": (
            "Тихая неделя — за последние {days} дн. ничего нового не появилось. "
            "Всё работает штатно; в следующем дайджесте будет больше."
        ),
        "quiet_day_line": (
            "Тихий день — за последний период ({days_phrase}) ничего нового. "
            "Всё работает штатно; в следующем дайджесте будет больше."
        ),
        # NB: the literal "TL;DR" stays — email_html keys the callout on it.
        "tldr_header": "## ⚡ Коротко (TL;DR)",
        "new_sources_header": "## 📰 Новые источники (за {window})",
        "concepts_header": "## 💡 Обновлённые концепты (за {window})",
        "synthesis_header": "## 🧪 Синтез за неделю",
        "attention_header": "## 📌 Требует внимания",
        "front_doors_header": "## 🗂 Входы в базу знаний",
        "front_door_line": "- **{label}:** {count_phrase} — в `{base_path}`.",
        "knowledge_base_label": "База знаний:",
        "reused_line": (
            "**🔁 Переиспользовано знание:** {count} существующих концептов "
            "переиспользовано при синтезе."
        ),
        "ops_health_label": "**⚠️ Состояние системы:**",
        "kb_changes_line": (
            "**🧠 Изменения базы знаний:** создано концептов: {created}, "
            "обновлено: {updated}."
        ),
        "debut_topic_caveat": (
            "🌱 Новая тема — первая неделя; подборка может шуметь, пока не "
            "настроятся правила отсева."
        ),
        "no_new_sources": "Новых источников нет.",
        "no_concept_updates": "Обновлений концептов нет.",
        "nothing_pending": "Ничего не ожидает.",
        "collected_label": "собрано",
        "more_by_credibility": "+{hidden} ещё — показаны топ-{shown} по надёжности источника",
        "more_in_base": "+{hidden} ещё в `{base_path}`",
        "tldr_most_active": "📰 Самая активная тема: **{topic}** ({share})",
        "tldr_share": "{count} из: {total_phrase}",
        "tldr_only_topic": "📰 {count_phrase} в теме **{topic}**",
        "tldr_worth_a_look": "🔎 Стоит прочитать: {titled}{marker}",
        "tldr_concepts_updated": "💡 Обновлено: {count_phrase}:",
        "header_summary": "{sources_phrase} в {topics_phrase}; {concepts_phrase}.",
        "daily_header_summary": "{sources_phrase} в {topics_phrase}.",
        "trust_single": "🟡 Учтён один домен издателя — проверьте утверждение",
        "front_door_lessons": "Уроки",
        "front_door_playbooks": "Плейбуки",
        "front_door_active_note": "активная заметка",
        "front_door_active_notes": "активных заметок",
        "front_door_reusable_method": "повторно применимый метод",
        "front_door_reusable_methods": "повторно применимых методов",
        "footer_audience": (
            "_🎚 Настроен уровень подачи «{level}» — агентные дайджесты и ответы "
            "в чате применяют его; эта детерминированная (без агента) сборка "
            "сохраняет фиксированные формулировки (docs/audience-levels.md)._"
        ),
        "footer_feedback": (
            "_💬 Обратная связь настраивает будущие дайджесты — ответьте, например: "
            "«слишком технично», «проще», «меньше <тема>», «выключи <источник>» "
            "(docs/feedback.md)._"
        ),
        "footer_report": (
            "_📊 Полный отчёт: [{name}]({name}) — откройте в браузере: вкладки и "
            "аудит по источникам._"
        ),
        "glossary_heading": "## 📖 Глоссарий",
        "trends_title": "📈 Тренды — {date}",
        "trends_intro": "_Сравнение последних {days} дней с предыдущими {days}._",
        "trends_volume_header": "📊 Объём по темам (эта неделя и прошлая)",
        "trends_volume_line": "**{topic}** — {current} за эту неделю ({arrow} {delta} к прошлой)",
        "trends_no_sources": "Новых источников на этой неделе нет.",
        "trends_new_topics": "🌱 Новые темы: {topics}",
        "trends_fading_topics": "💤 Затихающие темы: {topics}",
        "trends_tags_header": "🏷 Растущие теги",
        "trends_tag_line": "**{tag}** — обновлено концептов: {current} ({arrow} {delta})",
        "trends_activity_header": "⚡ Активность",
        "trends_inflow_line": "Приток: {current} за эту неделю ({arrow} {delta} к прошлой)",
        "trends_backlog_line": "Бэклог: {backlog} собранных источников ещё не откурировано",
        "trends_growth_header": "🧠 Рост базы знаний",
        "trends_created_line": "Создано концептов: {current} за эту неделю ({arrow} {delta} к прошлой)",
        "trends_sparkline_line": "Создано по неделям (последние {weeks} нед.): {spark} ({first} → {last})",
        "trends_updated_line": "Обновлено концептов за неделю: {count}",
        "trends_connected_line": "Наиболее связанные: {pretty}",
    },
}

# Russian noun forms (one, few, many) for the counted phrases the digest uses.
_RU_NOUNS: dict[str, tuple[str, str, str]] = {
    "new source": ("новый источник", "новых источника", "новых источников"),
    # Prepositional case — the only RU consumer is the "…в N темах" headline.
    "topic": ("теме", "темах", "темах"),
    "updated concept": ("обновлённый концепт", "обновлённых концепта", "обновлённых концептов"),
    "concept": ("концепт", "концепта", "концептов"),
    "day": ("день", "дня", "дней"),
    "source": ("источник", "источника", "источников"),
}


def resolve(language: str | None) -> str:
    """Normalize a configured language to a supported chrome table."""
    if language and language.strip().lower() in STRINGS:
        return language.strip().lower()
    return DEFAULT_LANGUAGE


def tr(language: str | None, key: str, **fmt: object) -> str:
    """The chrome string for `key` in `language`, en-fallback per key."""
    lang = resolve(language)
    template = STRINGS[lang].get(key) or STRINGS[DEFAULT_LANGUAGE][key]
    return template.format(**fmt) if fmt else template


def plural_ru(count: int, one: str, few: str, many: str) -> str:
    """Russian plural agreement: 1 день / 2 дня / 5 дней (and 11-14 → many)."""
    tail, tail2 = count % 10, count % 100
    if tail == 1 and tail2 != 11:
        return one
    if tail in (2, 3, 4) and tail2 not in (12, 13, 14):
        return few
    return many


def counted(language: str | None, count: int, noun_key: str) -> str:
    """A localized counted phrase, e.g. (ru, 2, "new source") → "2 новых источника".

    `noun_key` is the ENGLISH singular noun (the same key `_plural` uses), so en
    output stays byte-identical via the existing pluralizer path in callers; ru
    applies real three-form agreement.
    """
    if resolve(language) == "ru" and noun_key in _RU_NOUNS:
        one, few, many = _RU_NOUNS[noun_key]
        return f"{count} {plural_ru(count, one, few, many)}"
    return f"{count} {noun_key}{'' if count == 1 else 's'}"


__all__ = ["DEFAULT_LANGUAGE", "STRINGS", "counted", "plural_ru", "resolve", "tr"]
