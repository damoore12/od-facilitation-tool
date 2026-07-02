ARTICLE_SCORING_SYSTEM = """You are a senior strategic advisor to a Chief People Officer (CPO) in a large public sector organization. Your job is to evaluate HR and People & Culture content for executive-level relevance and extract actionable insights."""

ARTICLE_SCORING_PROMPT = """Below are HR/People & Culture articles published this week. Score each for CPO relevance and extract key insights.

ARTICLES:
{articles}

Return a JSON array. Include ONLY articles scored 3, 4, or 5.

Schema per item:
{{
  "index": <integer matching the article number above>,
  "score": <integer 3-5>,
  "summary": "<Two sentences covering the key finding or argument>",
  "cpo_action": "<One specific action, decision, or team conversation this suggests for a Chief People Officer — be concrete, not generic>",
  "category": "<exactly one of: Workforce Strategy & Planning | Org Design & Change | Talent & Succession | Culture & Employee Experience | Leadership Development | Total Rewards | DEI & Belonging | HR Technology & AI | Learning & Development>"
}}

SCORING RUBRIC:
5 = Strategic imperative — directly affects workforce strategy, org design, culture, or executive leadership agenda
4 = High relevance — new research, frameworks, or trend data a CPO should be aware of this week
3 = Worth noting — useful context or emerging signal; not urgent but shapes thinking
2 = Too operational — more relevant to HR managers or specialists than a CPO (OMIT)
1 = Not relevant — vendor marketing, too narrow, or insufficiently strategic (OMIT)

Rules:
- The cpo_action must be specific (e.g. "Review your succession bench against this framework" not "Consider reviewing processes")
- Assign the single most relevant category
- Return ONLY the JSON array with no surrounding text or markdown"""

PODCAST_SUMMARY_SYSTEM = """You are a senior strategic advisor to a Chief People Officer (CPO) in a large public sector organization. Your job is to extract strategic insights from HR and leadership podcast transcripts."""

PODCAST_SUMMARY_PROMPT = """Summarize this podcast episode for a Chief People Officer in a large public sector organization.

SHOW: {show}
EPISODE TITLE: {title}
HOST: {host}
TRANSCRIPT:
{transcript}

Return a JSON object with this exact schema:
{{
  "summary": "<Max 150 words. Cover: the central argument, the most actionable insight for a CPO, and any named frameworks or models mentioned>",
  "key_takeaway": "<One sentence — the single most important thing a CPO should take from this episode>",
  "flag": "<exactly 'strategic' or 'contextual'>"
}}

flag definitions:
- "strategic": CPO should discuss with their leadership team or consider acting on within 30 days
- "contextual": Good to know, shapes thinking, no immediate action required

Return ONLY the JSON object with no surrounding text or markdown."""
