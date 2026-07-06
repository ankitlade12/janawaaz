from janawaaz.adapters import rbi

# Structure mirrors rbi.org.in/notifications_rss.xml (RSS 2.0, CDATA titles).
# The draft item is synthetic — the live feed only shows the latest 10 items,
# and consultation-shaped ones appear sporadically; the filter is what we test.
FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>NOTIFICATIONS FROM RBI</title>
<item>
  <title><![CDATA[Draft Directions on Digital Lending — comments invited]]></title>
  <description><![CDATA[<p>RBI seeks public comments...</p>]]></description>
  <link>https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=99991</link>
  <pubDate>Mon, 29 Jun 2026 20:00:00 GMT</pubDate>
</item>
<item>
  <title><![CDATA[Auction of State Government Securities]]></title>
  <description><![CDATA[<p>Routine auction notice.</p>]]></description>
  <link>https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=88888</link>
  <pubDate>Fri, 03 Jul 2026 20:40:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_keeps_only_consultation_shaped_titles():
    records = rbi.parse_feed(FEED)
    assert len(records) == 1
    rec = records[0]
    assert "Digital Lending" in rec.title
    assert rec.source == "rbi"
    assert rec.external_id == "99991"
    assert rec.published_at is not None and rec.published_at.year == 2026
    assert rec.body_url.startswith("https://www.rbi.org.in/")


def test_malformed_feed_returns_empty():
    assert rbi.parse_feed("<not-xml") == []
