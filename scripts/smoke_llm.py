from influencer_outreach.config import Settings
from influencer_outreach.models import InfluencerProfile, Platform
from influencer_outreach.personalization import build_personalizer

s = Settings()
p = build_personalizer(s)
prof = InfluencerProfile(
    id="t1",
    name="Zen van Riel",
    platform=Platform.YOUTUBE,
    profile_url="https://youtube.com/x",
    follower_count=49200,
    engagement_rate=0.57,
    category="technology",
    content_themes=["technology", "ai"],
    contact_email="Not Found",
    recent_content_notes="I'm a Senior AI Engineer teaching you how to build with LLMs.",
)
m = p.personalize(prof)
print("SUBJ:", m.email_subject)
print("SIGNALS:", m.personalization_signals)
print("BODY:", m.email_body)
print("DM:", m.instagram_dm)
