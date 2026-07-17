"""Modular content-type catalog for the local WLHL Prompt Workspace."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    name: str
    category: str
    description: str
    default_instructions: str
    available_fields: tuple[str, ...]
    output_requirements: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


SHARED_FIELDS = (
    "main_angle", "central_lesson", "target_audience", "goal", "length", "tone", "cta",
    "additional_instructions", "language", "include_episode_references", "include_supporting_quotes",
    "include_source_notes",
)


def _template(template_id, name, category, description, instructions, outputs, extra_fields=()):
    return PromptTemplate(
        id=template_id,
        name=name,
        category=category,
        description=description,
        default_instructions=instructions,
        available_fields=SHARED_FIELDS + tuple(extra_fields),
        output_requirements=tuple(outputs),
    )


TEMPLATES = [
    _template("email", "Email", "Email", "A focused standalone email based on selected episodes.", "Write one useful email around one supported central idea.", ["Subject line", "Preview text", "Complete email"]),
    _template("newsletter", "Newsletter", "Email", "A WLHL educational newsletter with a practical takeaway.", "Write an English newsletter for The Weight Loss Hotline. Build it around one clear central lesson. Use only claims, stories, examples, and ideas supported by the supplied episode material. Do not invent quotes, facts, stories, or details. Write in Nick’s natural voice. Avoid generic motivational filler. Open with genuine interest rather than manipulative clickbait. Explain the lesson clearly, connect it to real life, include a practical takeaway, and end with a relevant low-pressure CTA.", ["Three subject line options", "Preview text", "Complete newsletter", "Episodes used", "Supporting concepts", "Supporting quotes only when explicitly present"], ("newsletter_angle",)),
    _template("promotional_email", "Promotional email", "Email", "An episode, membership, or offer promotion grounded in WLHL material.", "Write a clear promotional email without fake urgency, manipulation, or unsupported promises.", ["Three subject lines", "Preview text", "Complete promotional email", "CTA"]),
    _template("welcome_email", "Welcome email", "Email", "A welcoming introduction to WLHL and its philosophy.", "Welcome one reader warmly, explain what WLHL stands for, and set realistic expectations.", ["Subject line", "Preview text", "Complete welcome email"]),
    _template("reengagement_email", "Re-engagement email", "Email", "A respectful email for an inactive audience.", "Reconnect through a useful episode lesson. Do not use guilt, pressure, or fake scarcity.", ["Three subject lines", "Preview text", "Complete re-engagement email"]),
    _template("email_sequence", "Email sequence", "Email", "A connected sequence with a clear progression.", "Create a cohesive sequence in which each email has one job and naturally leads to the next.", ["Sequence overview", "Subject and preview text for each email", "Complete emails", "Sequence CTA"], ("number_of_emails", "email_goals", "sequence_cta")),
    _template("social_media", "Social media", "Social media", "A platform-neutral social post.", "Turn one supported episode idea into a useful, conversational social post.", ["Complete post", "Optional CTA"]),
    _template("instagram_caption", "Instagram caption", "Social media", "An Instagram caption designed for clear mobile reading.", "Write a natural Instagram caption with a strong first line and no engagement bait.", ["Caption", "Optional CTA", "Optional relevant hashtags"]),
    _template(
        "instagram_carousel",
        "Instagram carousel",
        "Social media",
        "A complete 10-slide Instagram carousel with copy, visual direction, caption, and hashtags.",
        """Create an English Instagram carousel for The Weight Loss Hotline using only the supplied episode material.

Build the carousel around one clear, specific central lesson. The carousel must contain exactly 10 slides and should feel like one connected story rather than ten unrelated tips.

Slide 1 must be a strong, accurate cover hook that creates curiosity without manipulative clickbait. Slides 2–3 should establish the relatable problem, mistaken belief, or situation. Slides 4–8 should develop the lesson using supported explanations, examples, stories, or practical steps. Slide 9 should give the reader a useful takeaway or reflection. Slide 10 should close naturally with a relevant, low-pressure CTA.

For every slide, provide:
- The slide number and purpose.
- Concise on-slide copy that remains readable on a phone.
- A specific image or design idea that supports the message instead of merely decorating it.
- Suggested visual hierarchy or emphasis when useful.

Visual ideas may include realistic everyday situations, podcast imagery, simple typography, objects, environments, diagrams, or symbolic concepts. Do not invent photographs, memories, events, physical transformations, before-and-after results, or personal details that are not supported by the selected episodes. Clearly identify when an idea requires an existing photo or episode asset rather than pretending that asset exists.

After the slides, write one complete Instagram caption in Nick’s natural voice. The caption should add context rather than repeat every slide. Include a direct but human CTA appropriate to the user’s request.

Provide a focused set of relevant hashtags. Avoid generic hashtag stuffing, misleading trending tags, and hashtags unsupported by the subject. Prefer specific weight-loss, behavior-change, mindset, episode, and WLHL terms that genuinely fit the carousel.

Preserve the meaning of Nick’s advice. Never invent quotes. If exact source wording is used, label it as an exact quote and include it only when explicitly present in the supplied material.""",
        [
            "Carousel title and central concept",
            "Exactly 10 numbered slides",
            "Purpose of each slide",
            "Concise on-slide text for each slide",
            "Image or design direction for each slide",
            "Visual hierarchy or emphasized words when useful",
            "Complete Instagram caption",
            "Relevant low-pressure CTA",
            "Focused set of relevant hashtags",
            "Episodes and source concepts used",
            "Exact-quote labels only when verified in the source material",
        ],
    ),
    _template("facebook_post", "Facebook post", "Social media", "A conversational Facebook post.", "Write for thoughtful reading and discussion without manufacturing controversy.", ["Complete Facebook post", "Optional CTA"]),
    _template("youtube_community_post", "YouTube community post", "Social media", "A concise post for the WLHL YouTube audience.", "Write a direct community post that invites useful reflection or episode viewing.", ["Complete community post", "Optional question or CTA"]),
    _template("threads_post", "Threads post", "Social media", "A concise Threads post or short thread.", "Use short natural paragraphs. Avoid vague inspirational statements.", ["Post or numbered thread", "Optional CTA"]),
    _template("linkedin_post", "LinkedIn post", "Social media", "A professional but human LinkedIn post.", "Translate the lesson without corporate jargon or performative thought leadership.", ["Complete LinkedIn post", "Optional CTA"]),
    _template("short_caption", "Reel or Short caption", "Social media", "A caption for vertical short-form video.", "Write a brief caption that adds context instead of repeating the hook.", ["Caption", "Optional CTA"]),
    _template("youtube_description", "YouTube description", "Video and podcast", "A searchable YouTube description based on episode content.", "Summarize the actual episode accurately and make the value clear without keyword stuffing.", ["Opening description", "Key topics", "Episode CTA", "Source episode reference"]),
    _template("podcast_show_notes", "Podcast show notes", "Video and podcast", "Structured show notes for an episode or topic collection.", "Create accurate, scannable notes that distinguish episode facts from summaries.", ["Overview", "Topics covered", "Key takeaways", "Episodes and links used"]),
    _template("youtube_titles", "YouTube title ideas", "Video and podcast", "Accurate title options without manipulative clickbait.", "Create compelling titles that promise only what the source material actually delivers.", ["Requested number of title options", "One-line rationale for strongest options"], ("number_of_options",)),
    _template("thumbnail_text", "Thumbnail text ideas", "Video and podcast", "Short thumbnail phrases that complement a title.", "Use few words, high clarity, and no unsupported claim.", ["Requested number of thumbnail options", "Suggested title pairing"], ("number_of_options",)),
    _template("short_hooks", "Short-form video hooks", "Video and podcast", "Opening hooks for Shorts, Reels, or clips.", "Create hooks grounded in explicit episode ideas. Label exact quotes versus adaptations.", ["Requested number of hooks", "Exact quote or adaptation label", "Source concept"], ("number_of_options",)),
    _template("short_titles", "Short-form video titles", "Video and podcast", "Compact titles for short-form clips.", "Keep titles specific, accurate, and easy to understand at a glance.", ["Requested number of title options"], ("number_of_options",)),
    _template("video_outline", "Video outline", "Video and podcast", "A structured video or podcast outline.", "Organize the selected lessons into a logical progression with practical examples.", ["Opening", "Ordered talking points", "Examples or stories", "Takeaway", "CTA"]),
    _template("blog_article", "Blog article", "Website and long-form", "A source-grounded long-form article.", "Write a useful article with natural headings, clear explanations, and no unsupported SEO filler.", ["Title options", "Article", "Practical takeaway", "Sources used"]),
    _template("landing_page", "Landing page copy", "Website and long-form", "A landing page grounded in WLHL positioning.", "Use clear benefits and evidence from supplied material. Do not exaggerate results.", ["Hero section", "Problem and approach", "Benefits", "CTA section"]),
    _template("sales_page_section", "Sales page section", "Website and long-form", "One focused section of a sales page.", "Write persuasive but honest copy with no fake urgency or guaranteed outcomes.", ["Section headline", "Body copy", "CTA"]),
    _template("faq_section", "FAQ section", "Website and long-form", "Questions and answers based on episode material.", "Answer only questions supported by the supplied material and flag gaps.", ["FAQ questions", "Clear answers", "Relevant episode references"]),
    _template("lead_magnet", "Lead magnet outline", "Website and long-form", "An actionable lead magnet structure.", "Build a practical outline that can be completed with available source material.", ["Promise and audience", "Section outline", "Exercises or takeaways", "Source map"]),
    _template("episode_summary", "Episode summary", "Research and internal use", "A faithful internal or public episode summary.", "Summarize the episode without adding interpretation that the source cannot support.", ["Concise summary", "Main lesson", "Key takeaways", "Source episode"]),
    _template("key_takeaways", "Key takeaways", "Research and internal use", "An actionable takeaway list from selected episodes.", "Extract and synthesize supported lessons. Distinguish direct advice from inference.", ["Key takeaways", "Supporting episode for each takeaway"]),
    _template("related_episodes", "Related episode recommendations", "Research and internal use", "A curated related-episode list.", "Explain why each selected episode is relevant to the topic.", ["Ranked episode recommendations", "Reason for each recommendation"]),
    _template("repurposing_plan", "Content repurposing plan", "Research and internal use", "A multi-format reuse plan for selected episodes.", "Recommend only assets that the selected source material can genuinely support.", ["Core theme", "Recommended assets by channel", "Source mapping", "Suggested priority"]),
    _template("content_calendar", "Content calendar ideas", "Research and internal use", "A practical calendar of source-backed content ideas.", "Create a realistic sequence that varies angle and format without repeating the same lesson.", ["Calendar table", "Topic", "Format", "Source episode", "CTA"]),
    _template("topic_brief", "Topic research brief", "Research and internal use", "A concise research brief across selected episodes.", "Synthesize the strongest supported ideas, tensions, examples, and gaps.", ["Executive summary", "Recurring themes", "Contrasting viewpoints", "Stories and quotes", "Source map", "Information gaps"]),
]

TEMPLATES_BY_ID = {template.id: template for template in TEMPLATES}
CATEGORIES = list(dict.fromkeys(template.category for template in TEMPLATES))
